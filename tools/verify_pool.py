"""驗收工具（C10）：核對池內每筆 evidence 的歸屬合理、thread 欄位正確、url 可連回。

用法：
    .venv/bin/python tools/verify_pool.py data/evidence/2026-10-02.jsonl
    .venv/bin/python tools/verify_pool.py data/evidence/2026-10-02.jsonl \
        --sample 20 --seed 20261002

判定標準（依 `docs/plan.md` 實作裁定 13、14、15、17）：

  - **歸屬**：一筆通過只要符合其中之一，並記錄來源供分布統計：
      1. `self`——留言／推文**自身**以精確版本提及該 row 的模型
         （走 `arena.collect.classify_attribution`，裁定 14）。
      2. `inherited`——row 帶 `thread`，且 `row.modelId == thread.modelId`，
         且 `thread.title` **或** `thread.body` 以精確版本提及該模型
         （裁定 15「主貼定歸屬、留言繼承」；裁定 17 補 `body` 供標題不帶版本號者）。
  - **thread 欄位**：帶 `thread` 的 row 其 `title`／`body` 要能通過歸屬、`modelId`
    要在清單內；`source == "x"` 的 row **不得**帶 `thread`（X 沒有留言結構）。
  - **url**：留言／推文的 `url` 與 `thread.url` 都實際連線，須 2xx 或 3xx。

輸出：逐筆結果表＋總計；任一筆不通過時結束碼 1。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arena.collect import classify_attribution, load_manual_models  # noqa: E402

CONFIG = Path(__file__).resolve().parents[1] / "config" / "models.yaml"
UA = "llm-arena-verify/1.0 (+https://github.com/jason-lab/llm-arena)"

SELF = "self"
INHERITED = "inherited"

# 抽樣明細裡每則文字顯示的字元數（夠看出在講什麼，又不至於洗版）。
EXCERPT_CHARS = 220


def _excerpt(text: object, limit: int = EXCERPT_CHARS) -> str:
    """把文字壓成單行摘要，供人工核對歸屬。"""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def attribution_source(
    row: dict, model: dict, catalogue: list[dict]
) -> tuple[str | None, str]:
    """回傳 ``(歸屬來源, 失敗理由)``；``None`` 表示通過。

    對應裁定 15／17 的兩種合法歸屬來源：留言自身精確提及，或繼承自
    ``thread.title``／``thread.body`` 的精確提及。自身提及優先——留言可以改判成
    主貼之外的另一個清單模型。

    ``thread.body``（v1.4，裁定 17）：當主貼標題不帶版本號、版本只出現在內文時，
    ``body`` 才是可佐證的歸屬憑據；兩者任一精確提及即可（先前只有 title 會不通過）。
    """
    verdict = classify_attribution(str(row.get("text") or ""), model, catalogue)
    if verdict.keep:
        return SELF, ""

    thread = row.get("thread")
    if isinstance(thread, dict):
        if thread.get("modelId") != row.get("modelId"):
            return None, (
                f"thread.modelId={thread.get('modelId')} 與 row.modelId="
                f"{row.get('modelId')} 不符，且留言自身未精確提及該模型"
            )
        title_model = next(
            (entry for entry in catalogue if entry["id"] == thread.get("modelId")), None
        )
        if title_model is None:
            return None, f"thread.modelId={thread.get('modelId')} 不在模型清單內"
        title_verdict = classify_attribution(
            str(thread.get("title") or ""), title_model, catalogue
        )
        if title_verdict.keep:
            return INHERITED, ""
        body_text = str(thread.get("body") or "").strip()
        if body_text:
            body_verdict = classify_attribution(body_text, title_model, catalogue)
            if body_verdict.keep:
                return INHERITED, ""
            return None, (
                "thread.title／body 皆未精確提及該模型"
                f"（title: {title_verdict.reason}；body: {body_verdict.reason}）"
            )
        return None, (
            f"thread.title 未精確提及該模型（{title_verdict.reason}），"
            "且無 thread.body 可佐證（裁定 17 的 v1.4 欄位）"
        )
    return None, f"留言自身未精確提及該模型（{verdict.reason}）且沒有 thread 欄位"


def check_urls(urls: list[str], *, timeout: float) -> dict[str, str]:
    """逐條連線；回傳 url → 結果字串。"""
    results: dict[str, str] = {}
    with httpx.Client(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": UA}
    ) as client:
        for url in urls:
            try:
                response = client.get(url)
                ok = 200 <= response.status_code < 400
                results[url] = f"{response.status_code} {'OK' if ok else 'FAIL'}"
            except httpx.HTTPError as exc:
                results[url] = f"ERR {type(exc).__name__}"
    return results


def thread_field_issues(rows: list[dict]) -> list[str]:
    """檢查 ``thread`` 欄位：有帶的必要欄位齊全，且 X 推文不得帶 ``thread``。

    v1.4（裁定 17）的 ``body`` 是**可選**欄位，不列入必要欄位；X 推文列即使只帶
    ``body`` 也算違規（X 沒有留言結構）。
    """
    thread_rows = [row for row in rows if isinstance(row.get("thread"), dict)]
    x_with_thread = [
        row for row in rows if row["source"] == "x" and "thread" in row
    ]
    issues = [
        f"{row['modelId']} {row['url']}：X 推文不該帶 thread 欄位（含 body）"
        for row in x_with_thread
    ]
    for row in thread_rows:
        thread = row["thread"]
        for field in ("url", "title", "modelId"):
            if not str(thread.get(field) or "").strip():
                issues.append(f"{row['url']}：thread 缺 {field}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="evidence jsonl")
    parser.add_argument("--sample", type=int, default=0, help="只抽樣 N 筆做 url 連線檢查（0＝全掃）")
    parser.add_argument("--seed", type=int, default=20261002, help="抽樣用的亂數種子（可重現）")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    catalogue = load_manual_models(CONFIG)
    by_id = {model["id"]: model for model in catalogue}

    # 1) 歸屬：自身精確提及 **或** 繼承自主貼 title／body 的精確提及。
    sources: Counter[str] = Counter()
    by_source_kind: Counter[str] = Counter()
    failures: list[tuple[dict, str]] = []
    per_row: dict[str, str] = {}
    for row in rows:
        model = by_id.get(row["modelId"])
        if model is None:
            failures.append((row, f"清單外 modelId {row['modelId']}"))
            continue
        source, reason = attribution_source(row, model, catalogue)
        if source is None:
            failures.append((row, reason))
            continue
        per_row[row["url"]] = source
        sources[source] += 1
        by_source_kind[f"{row['source']}/{source}"] += 1

    print(f"# 歸屬檢查（{len(rows)} 筆全掃）")
    print(
        f"歸屬來源分布：自身精確提及 {sources[SELF]}、"
        f"繼承自主貼（title／body）{sources[INHERITED]}、"
        f"合計 {sources[SELF] + sources[INHERITED]}"
    )
    for kind, count in sorted(by_source_kind.items()):
        print(f"  {kind:22s} {count}")
    print(f"不通過：{len(failures)}")
    for row, reason in failures[:20]:
        print(f"  - {row['modelId']} {row['url']}")
        print(f"      → {reason}")
        if isinstance(row.get("thread"), dict):
            print(f"      主貼標題：{_excerpt(row['thread'].get('title'), 100)}")
            if row["thread"].get("body"):
                print(f"      主貼內文：{_excerpt(row['thread'].get('body'), 100)}")

    # 2) thread 欄位：有帶的要正確，X 的不得帶。
    thread_rows = [row for row in rows if isinstance(row.get("thread"), dict)]
    x_rows = [row for row in rows if row["source"] == "x"]
    x_with_thread = [row for row in x_rows if "thread" in row]
    thread_issues = thread_field_issues(rows)
    print(f"\n# thread 欄位檢查")
    print(
        f"帶 thread 的 row：{len(thread_rows)}（reddit/hn 留言）；"
        f"X 推文 {len(x_rows)} 筆，其中不該帶 thread 的 {len(x_with_thread)} 筆；問題 {len(thread_issues)}"
    )
    for issue in thread_issues[:20]:
        print(f"  - {issue}")

    # 3) url 連線：抽樣或全掃（留言／推文 url ＋ thread url）。
    pool = rows
    if args.sample:
        rng = random.Random(args.seed)
        pool = sorted(rng.sample(rows, min(args.sample, len(rows))), key=lambda r: r["url"])
    urls = [row["url"] for row in pool]
    urls += [
        row["thread"]["url"] for row in pool if isinstance(row.get("thread"), dict)
    ]
    url_results = check_urls(sorted(set(urls)), timeout=args.timeout)
    url_failures = [url for url, note in url_results.items() if "OK" not in note]
    print(f"\n# 抽樣明細（{len(pool)} 筆，seed={args.seed}；人工核對用）")
    print(f"#   [來源] 自身＝留言自身精確提及該版本；繼承＝依主貼 title／body 的精確提及")
    for row in pool:
        note = url_results.get(row["url"], "?")
        mark = "自身" if per_row.get(row["url"]) == SELF else "繼承"
        print(f"  {note:10s} [{mark}] {row['modelId']:38s} {row['url']}")
        thread = row.get("thread")
        if isinstance(thread, dict):
            tnote = url_results.get(thread["url"], "?")
            body_note = (
                f"\n{' ' * 22}主貼內文：{_excerpt(thread.get('body'))}"
                if thread.get("body")
                else ""
            )
            print(
                f"  {tnote:10s} [主貼] {'':38s} {thread['url']}"
                f"\n{' ' * 22}主貼標題：{_excerpt(thread.get('title'))}{body_note}"
            )
        print(f"{' ' * 22}留言：{_excerpt(row.get('text'))}")
    print(f"\nurl 不通：{len(url_failures)}")
    for url in url_failures[:20]:
        print(f"  - {url} → {url_results[url]}")

    failed = len(failures) or len(thread_issues) or len(url_failures)
    print("\n結論：" + ("全部通過 ✅" if not failed else "有不通過項目 ❌"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())