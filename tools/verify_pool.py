"""驗收工具（C9）：核對新池每筆 evidence 的 url 可連回、且 text 精確提及該 row 的模型版本。

用法：
    .venv/bin/python tools/verify_pool.py data/evidence/2026-10-01.jsonl
    .venv/bin/python tools/verify_pool.py data/evidence/2026-10-01.jsonl --sample 20

判定標準（依 `docs/plan.md` 實作裁定 13、14）：
  - url：以 HEAD/GET 實際連線，reddit/hn/x 三種來源都要 2xx 或 3xx（永久連結可能重導向）。
  - text：走 `arena.collect.classify_attribution`（版本精確比對），必須 keep。
輸出：逐筆結果表＋總計；任一筆不通過時結束碼 1。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arena.collect import classify_attribution, load_manual_models  # noqa: E402

CONFIG = Path(__file__).resolve().parents[1] / "config" / "models.yaml"
UA = "llm-arena-verify/1.0 (+https://github.com/jason-lab/llm-arena)"


def check_urls(rows: list[dict], *, timeout: float) -> list[tuple[dict, str]]:
    """逐筆連回 url；回傳 (row, 結果字串)。"""
    results: list[tuple[dict, str]] = []
    with httpx.Client(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": UA}
    ) as client:
        for row in rows:
            url = row["url"]
            try:
                response = client.get(url)
                ok = 200 <= response.status_code < 400
                results.append((row, f"{response.status_code} {'OK' if ok else 'FAIL'}"))
            except httpx.HTTPError as exc:
                results.append((row, f"ERR {type(exc).__name__}"))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="evidence jsonl")
    parser.add_argument("--sample", type=int, default=0, help="只抽樣前 N 筆做 url 連線檢查")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    catalogue = load_manual_models(CONFIG)
    by_id = {model["id"]: model for model in catalogue}

    # 1) 歸屬：每筆 text 都必須精確提及該 row 的模型版本。
    attribution_failures: list[tuple[dict, str]] = []
    for row in rows:
        model = by_id.get(row["modelId"])
        if model is None:
            attribution_failures.append((row, f"清單外 modelId {row['modelId']}"))
            continue
        verdict = classify_attribution(row["text"], model, catalogue)
        if not verdict.keep:
            attribution_failures.append((row, verdict.reason))

    print(f"# 歸屬檢查（{len(rows)} 筆全掃）")
    print(f"不通過：{len(attribution_failures)}")
    for row, reason in attribution_failures[:20]:
        print(f"  - {row['modelId']} {row['url']} → {reason}")

    # 2) url 連線：抽樣或全掃。
    target = rows[: args.sample] if args.sample else rows
    print(f"\n# url 連線檢查（{len(target)} 筆）")
    url_results = check_urls(target, timeout=args.timeout)
    url_failures = [(row, note) for row, note in url_results if "OK" not in note]
    for row, note in url_results:
        print(f"  {note:10s} {row['modelId']:38s} {row['url']}")
    print(f"\nurl 不通：{len(url_failures)}")

    failed = len(attribution_failures) or len(url_failures)
    print("\n結論：" + ("全部通過 ✅" if not failed else "有不通過項目 ❌"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())