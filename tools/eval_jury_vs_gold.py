#!/usr/bin/env python3
"""評審團 vs gold 考卷驗證（C5 門檻，C8 版）。

輸入：
- ``--gold``：``arena calibrate make-evals`` 產生的 gold JSONL（laya-evals 格式）。
- ``--scored``：對同一批貼文跑 ``arena score`` 後的 evidence JSONL（judge=llm-jury@*）。
  text 以 sha256 對齊（gold 的 state.post 與 evidence 的 text）。

指標：
- 六個面向各自的 accuracy 與 macro-F1（三類）。
- 「常數 baseline」：該面向全部猜 ``not-discussed`` 的 accuracy——
  R4 研究警告 gold 約九成面向是 not-discussed，單看 accuracy 會誤導。
- 混淆矩陣（overall）。
- ECE 與信心單調性：評審團的 prob 是同票比例（4/4=1.0、3/4=0.75），
  只有兩個值，ECE 僅供參考；單調性檢查 prob=1.0 組 accuracy 應 ≥ prob=0.75 組。
- 來源切片（reddit／hn／x）。

門檻：accuracy ≥ 0.80（C5）。
輸出：markdown 報告（--out）與 JSON（--json）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

FACETS = ("overall", "quality", "speed", "tokenEfficiency", "tokenUsage", "priceValue")
LABELS = {
    "overall": ("positive", "negative", "neutral"),
    "quality": ("positive", "negative", "not-discussed"),
    "speed": ("positive", "negative", "not-discussed"),
    "tokenEfficiency": ("positive", "negative", "not-discussed"),
    "tokenUsage": ("positive", "negative", "not-discussed"),
    "priceValue": ("positive", "negative", "not-discussed"),
}


def macro_f1(golds: list[str], preds: list[str]) -> float:
    labels = set(golds) | set(preds)
    scores = []
    for label in labels:
        tp = sum(1 for g, p in zip(golds, preds) if g == label and p == label)
        fp = sum(1 for g, p in zip(golds, preds) if g != label and p == label)
        fn = sum(1 for g, p in zip(golds, preds) if g == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
    return sum(scores) / len(scores) if scores else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--scored", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("docs/calibration-report.md"))
    parser.add_argument("--json", type=Path, default=Path("docs/calibration-report.json"))
    args = parser.parse_args()

    gold_rows = [
        json.loads(line)
        for line in args.gold.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # gold 的 state.post → sha256；對到 scored evidence 的 text。
    scored: dict[str, dict] = {}
    for line in args.scored.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        digest = hashlib.sha256(record["text"].encode("utf-8")).hexdigest()
        scored[digest] = record

    pairs: list[tuple[dict, dict]] = []  # (gold row, scored record)
    missing = 0
    for row in gold_rows:
        digest = hashlib.sha256(row["state"]["post"].encode("utf-8")).hexdigest()
        record = scored.get(digest)
        if record is None or record.get("votes") is None:
            missing += 1
            continue
        pairs.append((row, record))

    report: dict = {
        "goldRows": len(gold_rows),
        "evaluated": len(pairs),
        "missingOrUnscored": missing,
        "judge": next((r.get("judge") for r in scored.values() if r.get("judge")), None),
        "facets": {},
    }

    lines = [
        "# 校準驗證報告（C8 評審團 vs gold）",
        "",
        f"- gold 列數：{len(gold_rows)}；實際可比對：{len(pairs)}；缺分/未評分：{missing}",
        f"- judge：`{report['judge']}`",
        "- 門檻（owner 裁定 2026-09-30）：overall ≥ 0.80；五面向改為「accuracy 須勝過"
        "常數 not-discussed baseline」，且「有討論的列數」< 10 的面向標『樣本不足』"
        "（一兩列之差純屬雜訊，不得據以下結論），呈現時須標註面向可信度。",
        "",
        "| 面向 | accuracy | 常數ND baseline | 有討論n | macro-F1 | n | 判定 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    passed_all = True
    for facet in FACETS:
        golds, preds, source_of = [], [], []
        for row, record in pairs:
            golds.append(row["expected"][facet])
            pred = record["votes"][facet]["label"]
            # 平手（label=None）視為「未作答」：一律算錯。
            preds.append(pred if pred is not None else "__no_answer__")
            source_of.append(row["tags"][0] if row.get("tags") else "?")
        n = len(golds)
        acc = sum(1 for g, p in zip(golds, preds) if g == p) / n if n else 0.0
        baseline = sum(1 for g in golds if g == "not-discussed") / n if n else 0.0
        discussed_n = sum(1 for g in golds if g != "not-discussed")
        f1 = macro_f1(golds, preds)
        if facet == "overall":
            passed = acc >= 0.80
            verdict = "✅" if passed else "❌"
        elif discussed_n < 10:
            passed = True  # 不构成失败，但如实标注样本不足
            verdict = "⚠️ 樣本不足"
        elif acc > baseline:
            passed = True
            verdict = "✅ 勝過 baseline"
        else:
            passed = False
            verdict = "❌ 未勝過 baseline"
        passed_all = passed_all and passed
        report["facets"][facet] = {
            "accuracy": round(acc, 4),
            "constantNDBaseline": round(baseline, 4),
            "discussedN": discussed_n,
            "macroF1": round(f1, 4),
            "n": n,
            "passed": passed,
            "verdict": verdict,
        }
        lines.append(
            f"| {facet} | {acc:.4f} | {baseline:.4f} | {discussed_n} | {f1:.4f} | {n} | "
            f"{verdict} |"
        )

    # overall 混淆矩陣（未作答併入 no_answer 欄）
    golds = [row["expected"]["overall"] for row, _ in pairs]
    preds = [
        record["votes"]["overall"]["label"] or "__no_answer__"
        for _, record in pairs
    ]
    labels = list(LABELS["overall"]) + ["__no_answer__"]
    lines += ["", "### overall 混淆矩陣（列=gold，欄=評審團）", ""]
    lines.append("| gold＼pred | " + " | ".join(labels) + " |")
    lines.append("| --- | " + " | ".join(["---"] * len(labels)) + " |")
    confusion: dict = {}
    for g in labels:
        row_counts = {
            p: sum(1 for gg, pp in zip(golds, preds) if gg == g and pp == p)
            for p in labels
        }
        confusion[g] = row_counts
        lines.append(f"| {g} | " + " | ".join(str(row_counts[p]) for p in labels) + " |")
    report["overallConfusion"] = confusion

    # ECE 與單調性（overall；prob 只有 1.0 與 0.75 兩個值；未作答不進 ECE）
    for facet in FACETS:
        buckets: dict[float, list[int]] = {}
        for row, record in pairs:
            prob = record["votes"][facet]["prob"]
            if prob is None:
                continue
            correct = int(record["votes"][facet]["label"] == row["expected"][facet])
            buckets.setdefault(round(prob, 4), []).append(correct)
        ece = 0.0
        rows_out = []
        for prob, corrects in sorted(buckets.items()):
            mean_acc = sum(corrects) / len(corrects)
            ece += len(corrects) / len(pairs) * abs(mean_acc - prob)
            rows_out.append(
                {"prob": prob, "n": len(corrects), "accuracy": round(mean_acc, 4)}
            )
        report["facets"][facet]["ece"] = round(ece, 4)
        report["facets"][facet]["confidenceBands"] = rows_out

    # 來源切片（overall）
    slices: dict[str, list[int]] = {}
    for (row, record), source in zip(pairs, source_of):
        slices.setdefault(source, []).append(
            int(record["votes"]["overall"]["label"] == row["expected"]["overall"])
        )
    report["overallBySource"] = {
        source: {"n": len(v), "accuracy": round(sum(v) / len(v), 4)}
        for source, v in sorted(slices.items())
    }
    lines += ["", "### overall 來源切片", ""]
    lines += [
        f"- {source}: n={v['n']}, accuracy={v['accuracy']:.4f}"
        for source, v in report["overallBySource"].items()
    ]

    lines += [
        "",
        f"## 總判定：{'✅ 過關（overall ≥ 0.80，各面向勝過或持平於常數 baseline）' if passed_all else '❌ 未達門檻'}",
        "",
        "> 注意：gold 由四家真實 LLM（qwen3.8-flash／mimo-v2.6-flash／minimax-m3／",
        "> nemotron-3.5-lightning）逐則 API 標註、≥3/4 多數成 gold，無人類 ground truth。",
        "> 評審團 prob 只有 {1.0, 0.75} 兩個值，ECE 僅供參考。",
        "> 「有討論 n」過小的面向（<10）無法有意義地評比，呈現時必須標註可信度不足。",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
