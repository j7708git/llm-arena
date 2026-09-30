#!/usr/bin/env python3
"""合併四家真實 LLM 標註 → gold 工作檔（v2）。

規則（照 annotation-guide v1.2「重標程序」）：每列每面向四家標籤，
≥3/4 同標籤 → 定案；否則該列任一面向無解 → 整列不回填（記 ambiguous），
與第一輪交接單的程序一致（「該列必須六格全數有解才回填」）。

輸出：``--out``（預設 data/calibration/annotation-worksheet-v2.jsonl），
格式與 annotation-worksheet.jsonl 相同，可直接餵 ``arena calibrate make-evals``。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

FACET_FIELDS = (
    "gold_overall",
    "gold_quality",
    "gold_speed",
    "gold_tokenEfficiency",
    "gold_tokenUsage",
    "gold_priceValue",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inputs", nargs="+", required=True, help="四家標註 JSONL（每家一檔）"
    )
    parser.add_argument(
        "--worksheet", type=Path, default=Path("data/calibration/annotation-worksheet.jsonl")
    )
    parser.add_argument(
        "--out", type=Path, default=Path("data/calibration/annotation-worksheet-v2.jsonl")
    )
    args = parser.parse_args()

    # annotator -> hash -> {field: label}
    votes: dict[str, dict[str, dict[str, str]]] = {}
    for path in args.inputs:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            digest = row["hash"]
            per_file = votes.setdefault(digest, {})
            for field in FACET_FIELDS:
                label = row.get(field)
                if isinstance(label, str) and label:
                    per_file.setdefault(field, {})[row.get("annotator", path)] = label

    worksheet = [
        json.loads(line)
        for line in args.worksheet.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    out_rows: list[dict] = []
    ambiguous = 0
    disagreements: Counter[str] = Counter()
    for row in worksheet:
        digest = row["hash"]
        per_file = votes.get(digest, {})
        golds: dict[str, str | None] = {}
        resolved = True
        for field in FACET_FIELDS:
            labels = per_file.get(field, {})
            if len(labels) < 4:  # 有標註員缺列
                resolved = False
                disagreements[f"{field}:缺答案"] += 1
                break
            top, count = Counter(labels.values()).most_common(1)[0]
            if count >= 3:
                golds[field] = top
                if count < 4:
                    disagreements[f"{field}:{top}"] += 1
            else:
                resolved = False
                disagreements[f"{field}:平手({dict(Counter(labels.values()))})"] += 1
                break
        if not resolved:
            ambiguous += 1
            continue
        out_rows.append({**row, **golds})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in out_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"gold 定案列數：{len(out_rows)} / {len(worksheet)}（ambiguous 排除 {ambiguous}）")
    for key, count in sorted(disagreements.items()):
        print(f"  {key}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
