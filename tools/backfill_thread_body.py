#!/usr/bin/env python3
"""回填 evidence 的 ``thread.body``（C11，實作裁定 17）。

背景：C10 的 20 筆留言（1.4%，含 ``r/ClaudeCode/comments/1wov62z``）其主貼**標題
不帶版本號**、版本號只在**內文**，``thread.title`` 單獨撐不起歸屬憑據。裁定 17
為 ``thread`` 新增**可選** ``body``（主貼內文，截斷至 1200 字元），本腳本負責把
既有池帶 ``thread`` 的 Reddit／HN 列，依 ``thread.url`` 重抓主貼內文補上 ``body``。

取文路徑（皆為公開、免 key 端點）：

- **Reddit**：以公開存檔 API ``https://arctic-shift.photon-reddit.com/api/posts/ids``
  一次抓多筆主貼的 ``selftext``（可整批回填、不受 Reddit 逐檔限流影響）；
  存檔查無者再退回公開 Atom feed ``https://www.reddit.com/comments/<id>/.rss``
  （取 ``t3_<id>`` entry 的 ``<content>`` 去標籤）。
  **注意**：collect 用的 Reddit shreddit 留言端點只回留言、**不含主貼內文**，
  故回填主貼內文不能沿用該路徑（已實測確認）。
- **Hacker News**：Algolia ``https://hn.algolia.com/api/v1/items/<id>`` 的
  ``text``（純連結貼文為空）。

設計：

- **不改評分／聚合行為**：只增寫 ``thread.body``；``hash``（以 ``text`` 計算）、
  ``votes``／``juryVotes``／``judge`` 全數原樣保留，不需重跑 ``arena score``。
- **冪等可重跑**：已帶非空 ``body`` 的討論串直接沿用、不再打網路；重跑輸出相同。
  另用 ``.tmp/thread-body-cache.json`` 記錄每次抓到的內文，讓被限流中斷的長跑能
  續抓（重跑只補未抓到的討論串，不打已抓過的）。
- **原子寫入**：同目錄暫存檔 + ``os.replace``，並保留原檔權限，不留半截檔。
- **失敗不硬補**：主貼已刪（404）或抓不到時，該列不補 ``body``，於報告列出。
- 全程不需要 API 金鑰；只用公開端點。

用法：
    .venv/bin/python tools/backfill_thread_body.py
    .venv/bin/python tools/backfill_thread_body.py data/evidence/2026-10-01.jsonl
    .venv/bin/python tools/backfill_thread_body.py --delay 4 --refresh
"""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import stat
import sys
import tempfile
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from arena.collect import MAX_TEXT_CHARS  # noqa: E402

DEFAULT_GLOB = "data/evidence/*.jsonl"
DEFAULT_CACHE = REPO / ".tmp" / "thread-body-cache.json"
UA = "llm-arena-backfill/1.0 (+https://github.com/jason-lab/llm-arena)"

# 公開的 Reddit 存檔 API（免 key）：一次以 ids 取多筆主貼（含 selftext）。
ARCTIC_SHIFT_POSTS = "https://arctic-shift.photon-reddit.com/api/posts/ids"
# 一次請求的 id 上限（實測 74 個 id 於 1.8 秒回傳；保守取 100）。
ARCTIC_SHIFT_CHUNK = 100
# 存檔中被移除／刪除的主貼內文佔位字串。
_REMOVED_TEXTS = {"[removed]", "[deleted]", "[ removed by reddit ]"}

# Reddit 永久連結中的貼文 id：``/comments/<id>/``。
_REDDIT_ID_RE = re.compile(r"/comments/([A-Za-z0-9]+)")
# HN 永久連結的 item id：``news.ycombinator.com/item?id=<id>``。
_HN_ITEM_ID_RE = re.compile(r"[?&]id=(\d+)")
_TAG_RE = re.compile(r"<[^>]+>")
# Reddit feed 在主貼內文後附的樣板尾巴。
_SUBMITTED_RE = re.compile(r"\s*submitted by\s*/u/\S+.*$", re.IGNORECASE)


def strip_html(fragment: str) -> str:
    """去標籤、反跳脫、壓空白（Reddit feed／HN text 都是 HTML 片段）。"""
    text = _TAG_RE.sub(" ", fragment or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def reddit_post_id(url: str) -> str | None:
    match = _REDDIT_ID_RE.search(url or "")
    return match.group(1) if match else None


def hn_item_id(url: str) -> str | None:
    match = _HN_ITEM_ID_RE.search(url or "")
    return match.group(1) if match else None


def _get_with_retry(
    client: httpx.Client, url: str, *, attempts: int, base_delay: float
) -> tuple[httpx.Response | None, str]:
    """帶退避的 GET；回傳 ``(回應, 失敗理由)``。404／410 立即回（不重試）。"""
    last = "未知錯誤"
    for attempt in range(attempts):
        try:
            response = client.get(url)
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}"
        else:
            if response.status_code in (404, 410):
                return None, f"{response.status_code}"
            if response.status_code == 200:
                return response, ""
            last = f"HTTP {response.status_code}"
            # 429：優先尊重 Retry-After。
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                time.sleep(min(float(retry_after), 60.0))
        # 指數退避 + 抖動，避免連續打爆 Reddit 的無憑證限流。
        sleep_for = min(base_delay * (2**attempt), 30.0)
        time.sleep(sleep_for + random.uniform(0, 1.0))
    return None, last


def fetch_reddit_body(
    client: httpx.Client, url: str, *, attempts: int, base_delay: float
) -> tuple[str, str]:
    """Reddit 主貼內文：取 Atom feed 中 ``t3_<id>`` entry 的 content。"""
    post_id = reddit_post_id(url)
    if post_id is None:
        return "", "無法從 url 取得貼文 id"
    feed_url = f"https://www.reddit.com/comments/{post_id}/.rss"
    response, reason = _get_with_retry(
        client, feed_url, attempts=attempts, base_delay=base_delay
    )
    if response is None:
        return "", reason
    entries = re.findall(r"<entry>(.*?)</entry>", response.text, re.S)
    if not entries:
        return "", "feed 內沒有 entry"
    target = f"t3_{post_id}"
    chosen = None
    for entry in entries:
        match = re.search(r"<id>(.*?)</id>", entry)
        if match and match.group(1).strip() == target:
            chosen = entry
            break
    if chosen is None:
        chosen = entries[0]
    content = re.search(r"<content[^>]*>(.*?)</content>", chosen, re.S)
    if content is None:
        return "", "entry 內沒有 content"
    # 內容是雙重 HTML 跳脫（XML 內再包 HTML）。
    text = html.unescape(html.unescape(content.group(1)))
    text = strip_html(text)
    text = _SUBMITTED_RE.sub("", text).strip()
    return text, ""


def _clean_selftext(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in _REMOVED_TEXTS:
        return ""
    return text


def fetch_reddit_bodies_bulk(
    client: httpx.Client,
    urls: list[str],
    *,
    attempts: int,
    base_delay: float,
) -> dict[str, str]:
    """以公開存檔 API 一次抓多筆 Reddit 主貼內文；回傳 ``{thread.url: body}``。

    存檔查無的 url 不會出現在結果裡，交由呼叫端退回 RSS；查到但內文為空／被刪的
    url 會以空字串出現（呼叫端視為「已確認無內文」，不再退回慢速 RSS）。
    """
    id_by_url: dict[str, str] = {}
    for url in urls:
        post_id = reddit_post_id(url)
        if post_id:
            id_by_url[url] = post_id
    result: dict[str, str] = {}
    ids = list(dict.fromkeys(id_by_url.values()))
    for start in range(0, len(ids), ARCTIC_SHIFT_CHUNK):
        chunk = ids[start : start + ARCTIC_SHIFT_CHUNK]
        response, _reason = _get_with_retry(
            client,
            f"{ARCTIC_SHIFT_POSTS}?ids={','.join(chunk)}",
            attempts=attempts,
            base_delay=base_delay,
        )
        if response is None:
            continue
        try:
            data = response.json().get("data", [])
        except (ValueError, AttributeError):
            continue
        by_id = {str(post.get("id")): post for post in data if isinstance(post, dict)}
        for url, post_id in id_by_url.items():
            post = by_id.get(post_id)
            if not post:
                continue
            # 找到但內文為空／被刪 → 記成空字串，讓呼叫端不再退回（慢的）RSS。
            result[url] = _clean_selftext(post.get("selftext"))
    return result


def fetch_hn_body(
    client: httpx.Client, url: str, *, attempts: int, base_delay: float
) -> tuple[str, str]:
    """HN 主貼內文：Algolia item 的 ``text``（純連結貼文為空）。"""
    item_id = hn_item_id(url)
    if item_id is None:
        return "", "無法從 url 取得 item id"
    response, reason = _get_with_retry(
        client,
        f"https://hn.algolia.com/api/v1/items/{item_id}",
        attempts=attempts,
        base_delay=base_delay,
    )
    if response is None:
        return "", reason
    try:
        payload = response.json()
    except ValueError:
        return "", "回應不是 JSON"
    return strip_html(str(payload.get("text") or "")), ""


def _fetch_body(
    client: httpx.Client,
    source: str,
    url: str,
    *,
    attempts: int,
    base_delay: float,
) -> tuple[str, str]:
    if source == "reddit":
        return fetch_reddit_body(client, url, attempts=attempts, base_delay=base_delay)
    if source == "hn":
        return fetch_hn_body(client, url, attempts=attempts, base_delay=base_delay)
    return "", f"來源 {source} 不支援"


def _load_cache(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items() if v}


def _save_cache(path: Path | None, cache: dict[str, str]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def backfill_file(
    path: Path,
    client: httpx.Client,
    *,
    attempts: int,
    base_delay: float,
    delay: float,
    refresh: bool,
    cache: dict[str, str],
    cache_path: Path | None,
) -> dict[str, object]:
    """回填單一 evidence 檔，回傳統計 dict。

    ``cache`` 是跨檔／跨次執行的已抓內文（key＝thread.url）；抓到即寫回 cache，
    讓長跑被限流中斷後重跑能續抓。
    """
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    # 既有 body：同一討論串只要有一列帶非空 body 就沿用（免重抓、保冪等）。
    existing: dict[str, str] = {}
    for row in rows:
        thread = row.get("thread")
        if isinstance(thread, dict) and thread.get("body"):
            existing.setdefault(str(thread.get("url") or ""), str(thread["body"]))

    thread_sources: dict[str, str] = {}
    for row in rows:
        thread = row.get("thread")
        if isinstance(thread, dict) and row.get("source") in ("reddit", "hn"):
            thread_sources.setdefault(str(thread.get("url") or ""), str(row["source"]))

    fetched: dict[str, str] = {} if refresh else {**existing, **cache}
    failures: list[tuple[str, str]] = []
    # 已有 body 的討論串直接沿用（冪等）；--refresh 時全部重抓。
    to_fetch = [url for url in thread_sources if url not in fetched]
    # Reddit：先用公開存檔 API 整批抓（快、不受逐檔限流）；查無者下面退回 RSS。
    reddit_urls = [url for url in to_fetch if thread_sources[url] == "reddit"]
    bulk = fetch_reddit_bodies_bulk(
        client, reddit_urls, attempts=attempts, base_delay=base_delay
    )
    # 依 url 排序，讓輸出可重現。
    for index, url in enumerate(sorted(to_fetch)):
        if url in bulk:
            body, reason = bulk[url], ""
        else:
            if index and delay:
                time.sleep(delay)
            body, reason = _fetch_body(
                client,
                thread_sources[url],
                url,
                attempts=attempts,
                base_delay=base_delay,
            )
        body = body.strip()
        if body:
            fetched[url] = body[:MAX_TEXT_CHARS]
            cache[url] = body[:MAX_TEXT_CHARS]
            _save_cache(cache_path, cache)
        else:
            failures.append((url, reason or "內文為空"))

    updated = 0
    new_bodies = 0
    for row in rows:
        thread = row.get("thread")
        if not isinstance(thread, dict):
            continue
        url = str(thread.get("url") or "")
        if url in fetched:
            if thread.get("body") != fetched[url]:
                updated += 1
                if not thread.get("body"):
                    new_bodies += 1
            thread["body"] = fetched[url]
        # 抓不到／內文為空：不硬補、不覆蓋既有值（保留原狀）。

    if updated:
        _atomic_write(path, rows)

    return {
        "path": str(path),
        "rows": len(rows),
        "thread_rows": sum(
            1 for row in rows if isinstance(row.get("thread"), dict)
        ),
        "threads": len(thread_sources),
        "fetched": len([u for u in to_fetch if u in fetched]),
        "new_bodies": new_bodies,
        "updated_rows": updated,
        "failures": failures,
        "written": bool(updated),
    }


def _atomic_write(path: Path, rows: list[dict]) -> None:
    """原子覆寫 jsonl（保留原檔權限），格式與管線一致（每行一筆、ensure_ascii=False）。"""
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="evidence jsonl（預設 data/evidence/*.jsonl，不含 archive/）",
    )
    parser.add_argument("--attempts", type=int, default=6, help="單一請求重試次數")
    parser.add_argument("--delay", type=float, default=3.0, help="討論串之間的間隔秒數")
    parser.add_argument("--base-delay", type=float, default=3.0, help="退避基準秒數")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--refresh", action="store_true", help="連已帶 body 的討論串也重抓"
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE,
        help="已抓內文的續抓快取（預設 .tmp/thread-body-cache.json）",
    )
    args = parser.parse_args()

    paths = args.paths or sorted(
        p for p in Path().glob(DEFAULT_GLOB) if "archive" not in p.parts
    )
    if not paths:
        print("找不到 evidence 檔。", file=sys.stderr)
        return 1

    cache = _load_cache(args.cache)
    client = httpx.Client(
        timeout=args.timeout,
        headers={"User-Agent": UA},
        follow_redirects=True,
    )
    reports = []
    with client:
        for path in paths:
            report = backfill_file(
                path,
                client,
                attempts=args.attempts,
                base_delay=args.base_delay,
                delay=args.delay,
                refresh=args.refresh,
                cache=cache,
                cache_path=args.cache,
            )
            reports.append(report)
            print(
                f"[{report['path']}] rows={report['rows']} "
                f"thread_rows={report['thread_rows']} threads={report['threads']} "
                f"fetched={report['fetched']} 新補 body={report['new_bodies']} "
                f"更新列={report['updated_rows']} 寫回={'是' if report['written'] else '否'}"
            )
            for url, reason in report["failures"]:  # type: ignore[union-attr]
                print(f"  - 未補：{url} → {reason}")

    total_new = sum(int(r["new_bodies"]) for r in reports)
    total_fail = sum(len(r["failures"]) for r in reports)  # type: ignore[arg-type]
    print(f"\n合計：新補 body 的列 {total_new}；未補（已刪／內文空）{total_fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
