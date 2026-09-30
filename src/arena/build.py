"""`arena build` 的實作（任務 C4）：由 evidence 的 ``votes`` 聚合出 ``data/scores.json``。

資料契約與公式以 ``docs/plan.md`` 為準（schema v1.1 與實作裁定第 10 條）：

- **只計已評分的列**：``judge`` 為本次評分器（laya，pin 版）**且** ``votes`` 六鍵完整；
  未評分（``votes`` 為 null）或評分器／投票不符的列跳過，並在 stderr 報數量。
- 每面向 ``P``＝positive 數、``N``＝negative 數、``n = P + N``
  （``not-discussed`` 不計入 P／N，也不計入 n）。``n == 0`` → 該面向 ``null``
  （「資料不足」，**不得**當成 50）。
- ``raw = (P - N) / n``、``dimScore = 50*(raw+1)*n/(n+K) + 50*K/(n+K)``，
  ``K = 10`` 為偽樣本數收縮（n=10 收一半、n=90 收 10%；樣本越小越往 50 靠攏），
  四捨五入到小數第一位。
- ``score``＝非 null 面向的加權平均（權重 ``meta.weights``，剔除 null 後重歸一），
  同樣到小數第一位。為了讓榜上數字可手算回推，**以四捨五入後的面向分數**計算。
- 模型層 ``confidence``＝overall 正面率的 **Wilson 95% 下界**（樣本信任度）。
- ``sampleSize == 0`` 的模型**不入榜**，並列在 ``meta.notes`` 交代。
- ``evidence`` 參照列出該模型**全部**的 evidence 列（含未評分者），
  供站方回溯到原始貼文。

輸出採**原子寫入**：先寫同目錄的暫存檔、``fsync``、chmod 644，寫完以現成的
:func:`arena.validate.validate_path` 驗證；不合規則就刪掉暫存檔、**不覆蓋原檔**並
以非 0 結束碼收場。重跑對同一份輸入除 ``generatedAt``／``updatedAt`` 外逐位元組相同。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from arena.jury import JURY_MEMBERS, jury_judge
from arena.schema import (
    DEFAULT_WEIGHTS,
    FACET_DIMENSION_IDS,
    JURY_SCHEMA_VERSION,
    OVERALL_VOTE_ID,
    VOTE_IDS,
)
from arena.validate import validate_path

EXIT_OK = 0
EXIT_ERROR = 1

# 取樣窗口天數預設值（``--window-days`` 未給時）。
DEFAULT_WINDOW_DAYS = 30
# 預設輸入：所有 evidence 檔與 C1 產出的模型清單。
DEFAULT_EVIDENCE_GLOB = "data/evidence/*.jsonl"
DEFAULT_MODELS = Path("data/models.json")
# 預設輸出：網站唯一需要的輸入檔。
DEFAULT_OUTPUT = Path("data/scores.json")

# 評分器身分（C8 起改 LLM 評審團，2026-09-30；laya 已淘汰——judge 不符的列會被
# 跳過並計入 mismatched 統計，重跑 `arena score` 即回歸）。
JURY_JUDGE_ID = jury_judge(JURY_MEMBERS)  # 例：llm-jury@cd50a7e9

# 偽樣本數收縮常數：越大越往 50 靠攏（實作裁定第 10 條）。
K_SHRINKAGE = 10
# Wilson 95% 信賴區間的 z 值。
WILSON_Z = 1.96

# meta 的固定文案。
KIND = "community-sentiment"
DISCLAIMER = "社群聲量代理指標，非 benchmark"
# 窗口偏誤說明；後面會接被排除模型的清單。
WINDOW_NOTE = "近 30 天窗口，會偏袒近期熱門模型。"

# 面向 id → 站方顯示名稱（順序由 schema 的 FACET_DIMENSION_IDS 決定）。
DIMENSION_LABELS: dict[str, str] = {
    "quality": "智能",
    "speed": "速度",
    "tokenEfficiency": "Token 效率",
    "tokenUsage": "Token 用量",
    "priceValue": "CP 值",
}


class BuildError(RuntimeError):
    """build 流程中可預期的錯誤（檔案問題、格式不符等）。"""


@dataclass(frozen=True)
class EvidenceRow:
    """一則 evidence 列（含回溯用的參照位置）。"""

    ref: str
    model_id: str
    source: str
    judge: str | None
    votes: dict[str, Any] | None


def _utcnow_iso() -> str:
    """目前 UTC 時間的 ISO 8601 字串（秒精度、以 ``Z`` 結尾）。"""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def dimension_score(positive: int, negative: int) -> float | None:
    """由單一面向的 P／N 算出 0～100 分；``n == 0`` 回 ``None``（資料不足）。

    公式見模組 docstring；回傳值四捨五入到小數第一位。
    """
    n = positive + negative
    if n == 0:
        return None
    raw = (positive - negative) / n
    value = 50 * (raw + 1) * n / (n + K_SHRINKAGE) + 50 * K_SHRINKAGE / (n + K_SHRINKAGE)
    return round(value, 1)


def wilson_lower_bound(positive: int, sample_size: int) -> float:
    """overall 正面率的 Wilson 95% 下界（z=1.96）。

    ``sample_size == 0`` 時無從估計，回 ``0``（最保守的信心值）。
    標準公式：``(p + z²/2n - z·sqrt(p(1-p)/n + z²/4n²)) / (1 + z²/n)``。
    """
    if sample_size <= 0:
        return 0.0
    p = positive / sample_size
    z2 = WILSON_Z * WILSON_Z
    denominator = 1 + z2 / sample_size
    centre = p + z2 / (2 * sample_size)
    margin = WILSON_Z * math.sqrt(
        p * (1 - p) / sample_size + z2 / (4 * sample_size * sample_size)
    )
    return max(0.0, (centre - margin) / denominator)


def _is_countable(row: EvidenceRow) -> bool:
    """可納入聚合的列：評分器為現任評審團且六題投票完整。"""
    if row.votes is None:
        return False
    if row.judge != JURY_JUDGE_ID:
        return False
    return set(row.votes) == set(VOTE_IDS)


def _load_rows(paths: Sequence[Path]) -> list[EvidenceRow]:
    """讀入所有 evidence 檔；JSON 壞掉或欄位不合法時丟 :class:`BuildError`。"""
    rows: list[EvidenceRow] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BuildError(f"{path}：無法讀取檔案：{exc}") from exc

        for line_number, raw in enumerate(text.splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise BuildError(
                    f"{path} 第 {line_number} 行：JSON 解析失敗：{exc.msg}"
                ) from exc
            if not isinstance(payload, dict):
                raise BuildError(f"{path} 第 {line_number} 行：每行必須是 JSON 物件")
            model_id = payload.get("modelId")
            source = payload.get("source")
            if not isinstance(model_id, str) or not model_id:
                raise BuildError(f"{path} 第 {line_number} 行：缺少 modelId")
            if not isinstance(source, str) or not source:
                raise BuildError(f"{path} 第 {line_number} 行：缺少 source")
            votes = payload.get("votes")
            if votes is not None and not isinstance(votes, dict):
                raise BuildError(f"{path} 第 {line_number} 行：votes 必須是物件或 null")
            judge = payload.get("judge")
            if judge is not None and not isinstance(judge, str):
                raise BuildError(f"{path} 第 {line_number} 行：judge 必須是字串或 null")
            rows.append(
                EvidenceRow(
                    ref=f"evidence/{path.name}#l{line_number}",
                    model_id=model_id,
                    source=source,
                    judge=judge,
                    votes=votes,
                )
            )
    return rows


def _load_models(path: Path) -> dict[str, dict[str, Any]]:
    """讀入 ``data/models.json``，回傳 id → 模型物件；檔案不存在時回空 map。"""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"{path}：無法讀取模型清單：{exc}") from exc
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for entry in models:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]:
            index[entry["id"]] = entry
    return index


def _weighted_score(
    dimensions: Mapping[str, float | None], weights: Mapping[str, float]
) -> float:
    """非 null 面向的加權平均（權重剔除 null 後重歸一），小數第一位。

    理論上可以所有面向都 null（貼文只談總評、每個面向都 ``not-discussed``）；
    此時無從加權，回中立值 50.0 讓 schema 的 ``score``（必填 float）成立。
    """
    total_weight = 0.0
    accumulated = 0.0
    for facet in FACET_DIMENSION_IDS:
        value = dimensions.get(facet)
        if value is None:
            continue
        weight = weights.get(facet, 0.0)
        if weight <= 0:
            continue
        accumulated += weight * value
        total_weight += weight
    if total_weight <= 0:
        return 50.0
    return round(accumulated / total_weight, 1)


def _aggregate(
    model_id: str,
    rows: Sequence[EvidenceRow],
    models_index: Mapping[str, dict[str, Any]],
    weights: Mapping[str, float],
    generated_at: str,
) -> dict[str, Any]:
    """把單一模型的所有列聚合成一個 ``models[]`` 條目。"""
    counted = [row for row in rows if _is_countable(row)]
    sample_size = len(counted)

    facet_positive = {facet: 0 for facet in FACET_DIMENSION_IDS}
    facet_negative = {facet: 0 for facet in FACET_DIMENSION_IDS}
    overall_positive = 0
    mentions: dict[str, int] = {}

    for row in counted:
        votes = row.votes
        assert votes is not None  # _is_countable 已保證
        mentions[row.source] = mentions.get(row.source, 0) + 1
        for facet in FACET_DIMENSION_IDS:
            label = votes[facet].get("label")
            if label == "positive":
                facet_positive[facet] += 1
            elif label == "negative":
                facet_negative[facet] += 1
        if votes[OVERALL_VOTE_ID].get("label") == "positive":
            overall_positive += 1

    dimensions = {
        facet: dimension_score(facet_positive[facet], facet_negative[facet])
        for facet in FACET_DIMENSION_IDS
    }
    dimension_samples = {
        facet: facet_positive[facet] + facet_negative[facet]
        for facet in FACET_DIMENSION_IDS
    }

    entry = models_index.get(model_id, {})
    name = entry.get("name") or model_id
    provider = entry.get("provider") or "unknown"
    price = entry.get("priceUsdPerMTok")

    return {
        "id": model_id,
        "name": name,
        "provider": provider,
        "score": _weighted_score(dimensions, weights),
        "dimensions": dimensions,
        "priceUsdPerMTok": price,
        "dimensionSamples": dimension_samples,
        "sampleSize": sample_size,
        "positiveRate": (overall_positive / sample_size) if sample_size else 0.0,
        "confidence": wilson_lower_bound(overall_positive, sample_size),
        # 計數與 sampleSize 同一組（已評分的列）；evidence 參照則含全部列。
        "mentionsBySource": dict(sorted(mentions.items())),
        "evidence": [row.ref for row in rows],
        "updatedAt": generated_at,
    }


def build_document(
    rows: Sequence[EvidenceRow],
    models_index: Mapping[str, dict[str, Any]],
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    weights: Mapping[str, float] | None = None,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], int, int]:
    """聚合出完整 ``scores.json`` 物件；回傳 ``(document, 未評分列數, 不符列數)``。

    ``rows`` 依檔案順序傳入，同模型的 evidence 參照順序因此固定、可重現。
    """
    resolved_weights = dict(weights) if weights is not None else dict(DEFAULT_WEIGHTS)
    resolved_generated = generated_at or _utcnow_iso()

    # 依 evidence 出現順序分組，保留可重現的參照順序。
    grouped: dict[str, list[EvidenceRow]] = {}
    for row in rows:
        grouped.setdefault(row.model_id, []).append(row)

    unscored = sum(1 for row in rows if row.votes is None)
    mismatched = sum(
        1 for row in rows if row.votes is not None and not _is_countable(row)
    )
    countable = [row for row in rows if _is_countable(row)]
    sources_covered = sorted({row.source for row in countable})

    # 候選模型＝模型清單裡的 id ∪ evidence 出現過的 id。
    candidate_ids = sorted(set(models_index) | set(grouped))

    entries: list[dict[str, Any]] = []
    excluded: list[str] = []
    for model_id in candidate_ids:
        entry = _aggregate(
            model_id,
            grouped.get(model_id, []),
            models_index,
            resolved_weights,
            resolved_generated,
        )
        if entry["sampleSize"] == 0:
            excluded.append(model_id)
            continue
        entries.append(entry)

    # 排行榜：分數高到低；同分以 id 為序，確保輸出可重現。
    entries.sort(key=lambda item: (-item["score"], item["id"]))

    meta: dict[str, Any] = {
        "schemaVersion": JURY_SCHEMA_VERSION,
        "generatedAt": resolved_generated,
        "windowDays": window_days,
        "kind": KIND,
        "disclaimer": DISCLAIMER,
        "judge": {
            "kind": "llm-jury",
            "members": list(JURY_MEMBERS),
            # gold 考卷驗證通過前一律 false（不得謊稱）。
            "calibrated": False,
        },
        "dimensions": [
            {"id": facet, "label": DIMENSION_LABELS[facet]}
            for facet in FACET_DIMENSION_IDS
        ],
        "weights": resolved_weights,
        "sourcesCovered": sources_covered,
        "notes": _build_notes(excluded),
    }
    return {"meta": meta, "models": entries}, unscored, mismatched


def _build_notes(excluded: Sequence[str]) -> str:
    """窗口偏誤說明 + 被排除模型清單（``sampleSize == 0``，含零 evidence 的 id）。"""
    if not excluded:
        return WINDOW_NOTE
    return WINDOW_NOTE + "未列入榜（樣本數 0）：" + "、".join(excluded) + "。"


def _write_document(path: Path, document: Mapping[str, Any]) -> list[str]:
    """原子寫入並以 :func:`validate_path` 驗證；回傳錯誤清單（成功為空）。

    先寫同目錄暫存檔（``.json`` 結尾，讓 ``validate_path`` 依副檔名分流）、fsync、
    chmod 644、驗證，通過才 ``os.replace`` 覆蓋原檔。任何失敗都不會動到原檔，
    也不會留下暫存檔。
    """
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    directory = path.parent if str(path.parent) else Path(".")
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".json", dir=str(directory)
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o644)
        errors = validate_path(temp_path)
        if errors:
            temp_path.unlink(missing_ok=True)
            return errors
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return []


def run(args: argparse.Namespace) -> int:
    """`arena build` 的進入點。"""
    try:
        window_days = int(getattr(args, "window_days", None) or DEFAULT_WINDOW_DAYS)
        if window_days < 1:
            print("arena build：--window-days 必須 >= 1。", file=sys.stderr)
            return EXIT_ERROR

        output = Path(getattr(args, "output", None) or DEFAULT_OUTPUT)
        paths = sorted(Path().glob(DEFAULT_EVIDENCE_GLOB))
        if not paths:
            print(
                f"arena build：找不到 evidence 檔（預設 {DEFAULT_EVIDENCE_GLOB}）。",
                file=sys.stderr,
            )
            return EXIT_ERROR

        rows = _load_rows(paths)
        models_index = _load_models(DEFAULT_MODELS)
        document, unscored, mismatched = build_document(
            rows, models_index, window_days=window_days
        )

        if unscored:
            print(
                f"arena build：跳過 {unscored} 筆未評分（votes 為 null）的 evidence。",
                file=sys.stderr,
            )
        if mismatched:
            print(
                f"arena build：跳過 {mismatched} 筆 judge 不符或 votes 不完整的 evidence。",
                file=sys.stderr,
            )

        errors = _write_document(output, document)
        if errors:
            for error in errors:
                print(f"arena build：產出未通過 validate：{error}", file=sys.stderr)
            print(
                f"arena build：{output} 未更新（原檔保持不變）。", file=sys.stderr
            )
            return EXIT_ERROR
    except BuildError as exc:
        print(f"arena build：{exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("arena build：已取消。", file=sys.stderr)
        return EXIT_ERROR

    models = document["models"]
    print(f"arena build：已寫入 {output}（{len(models)} 個模型）。")
    for entry in models:
        print(f"  {entry['id']}: {entry['score']}")
    return EXIT_OK


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """把 build 的參數掛上 argparse 子解析器（cli.py 會自動呼叫）。"""
    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        metavar="N",
        help=f"取樣窗口天數（預設 {DEFAULT_WINDOW_DAYS}）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"輸出檔路徑（預設 {DEFAULT_OUTPUT}）",
    )


__all__ = [
    "DEFAULT_EVIDENCE_GLOB",
    "DEFAULT_MODELS",
    "DEFAULT_OUTPUT",
    "DEFAULT_WINDOW_DAYS",
    "DIMENSION_LABELS",
    "DISCLAIMER",
    "EXIT_ERROR",
    "EXIT_OK",
    "JUDGE_MODEL",
    "JUDGE_REVISION",
    "K_SHRINKAGE",
    "WILSON_Z",
    "BuildError",
    "EvidenceRow",
    "add_arguments",
    "build_document",
    "dimension_score",
    "run",
    "wilson_lower_bound",
]
