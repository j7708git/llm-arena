"""人工標註工作檔的抽樣與評測集轉換（任務 C5a）。

設計與抽樣方法以 ``docs/plan.md`` §6（評審契約與校準）為準，欄位語意以
``docs/plan.md`` §4（evidence 資料契約）與實作裁定 8 為準：

- **分層抽樣**（R1 步驟 1）：來源（reddit／hn／x）× 信心帶
  （``answer_confidence < 0.70`` 為低信心、加權 2–3 倍）。預設以 ``overall`` 的
  ``prob`` 分帶（總評是主要標註目標）；同一份工作檔每筆都標六個面向，之後 C5
  分析各面向 ECE 時再以**該面向自己的** ``prob`` 分帶（函式 :func:`band_counts`）。
  目標 n=150（上限 200），每來源至少 25 則（R1 步驟 1 第 2 點）。
- **排除**：``data/samples/`` 種子、重複 ``hash``、少於 ~10 字的碎片（R1 步驟 1 第 1 點）。
- **防 anchoring**（R1 步驟 1 第 5 點）：工作檔**絕不放**模型預測的 label／prob；
  要對照時用 ``hash`` join 回 evidence（:func:`make_eval_rows` 就是這樣做的）。
- **固定亂數種子**：同池同 seed 重跑產出位元組相同的工作檔（:data:`SAMPLE_SEED`）。

三個子命令（不進 ``cli.py``，以 ``python -m arena.calibrate`` 執行）：

- ``sample``     由 evidence 抽出工作檔：``data/calibration/annotation-worksheet.jsonl``
  ＋同名的 ``.meta.json``（記 seed、分層實抽數，可重現）。
- ``make-evals`` 把標完的工作檔（``hash`` join 回 evidence）轉成 ``laya-evals`` 可吃的
  gold JSONL（``state``／``questions``／``expected``／``tags``）。
- ``stats``      標註進度（已完成／部分／未標）與各面向非空數，方便回報。

題目定義**從 :mod:`arena.score` 匯入**（``QUESTION``），不複製貼上，避免 rubric 漂移。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from arena.schema import OVERALL_VOTE_ID, VOTE_IDS
from arena.score import QUESTION

EXIT_OK = 0
EXIT_ERROR = 1

# --- 抽樣常數（R1 筆記「步驟 1」）-----------------------------------------
# 固定亂數種子：同池同 seed 重跑必須產出相同清單（驗收條件）。
SAMPLE_SEED = 20260929
# 目標 n=150；下限 100、上限 200（R1 步驟 5 的樣本數理由）。
TARGET_N = 150
MIN_N = 100
CAP_N = 200
# 每來源至少 25 則（R1 步驟 1 第 2 點）。
MIN_PER_SOURCE = 25
# 低信心帶門檻與加權倍數（R1 步驟 1 第 3 點：<0.70 抽 2–3 倍）。
LOW_CONFIDENCE_THRESHOLD = 0.70
LOW_CONFIDENCE_WEIGHT = 2.5
# 少於此字元的碎片不抽（R1 步驟 1 第 1 點）。
MIN_TEXT_LEN = 10

DEFAULT_EVIDENCE_GLOB = "data/evidence/*.jsonl"
DEFAULT_WORKSHEET = "data/calibration/annotation-worksheet.jsonl"
DEFAULT_GOLD = "data/calibration/gold.jsonl"

LOW = "low"
HIGH = "high"

# 六個 gold 欄位（overall 在前，順序同 VOTE_IDS）。
GOLD_FIELDS: tuple[str, ...] = tuple(f"gold_{qid}" for qid in VOTE_IDS)
# 工作檔的完整欄位（順序即輸出順序）。**不得**出現任何預測欄位。
WORKSHEET_FIELDS: tuple[str, ...] = (
    "hash",
    "modelId",
    "source",
    "url",
    "postedAt",
    "text",
    *GOLD_FIELDS,
    "notes",
    "annotator",
    "annotatedAt",
)

# overall 用 positive／negative／neutral；面向用 positive／negative／not-discussed。
OVERALL_LABELS: tuple[str, ...] = ("positive", "negative", "neutral")
FACET_LABELS: tuple[str, ...] = ("positive", "negative", "not-discussed")


class CalibrateError(RuntimeError):
    """抽樣或轉換流程中可預期的錯誤（檔案問題、欄位不符、標籤非法等）。"""


@dataclass(frozen=True)
class Candidate:
    """一則可抽樣的 evidence：保留六題投票，供分層與後續分析使用。"""

    hash: str
    modelId: str
    source: str
    url: str
    postedAt: str
    text: str
    votes: dict[str, dict[str, Any]]

    def prob(self, qid: str) -> float:
        """指定面向的校準機率（``votes.<qid>.prob``）。"""
        return float(self.votes[qid]["prob"])


@dataclass
class LoadStats:
    """載入與過濾的計數，供回報與測試斷言。"""

    files: list[str] = field(default_factory=list)
    seen: int = 0
    scored: int = 0
    excluded_duplicates: int = 0
    excluded_fragments: int = 0
    excluded_unscored: int = 0

    @property
    def candidates(self) -> int:
        return self.scored


@dataclass
class SampleResult:
    """抽樣結果：選中的候選＋分層計數（皆決定性）。"""

    selected: list[Candidate]
    strata: dict[str, int]
    by_source: dict[str, int]
    seed: int
    band_question: str


# --- 載入與過濾 -------------------------------------------------------------


def _is_sample_path(path: Path) -> bool:
    """``data/samples/`` 底下的檔案不是真資料，一律排除（種子）。"""
    return "samples" in path.parts


def _is_scored(record: dict[str, Any]) -> bool:
    """votes 六鍵完整（每鍵是 dict、有 label 與數值 prob）才算已評分。"""
    votes = record.get("votes")
    if not isinstance(votes, dict):
        return False
    for qid in VOTE_IDS:
        vote = votes.get(qid)
        if not isinstance(vote, dict):
            return False
        if "label" not in vote or not isinstance(vote.get("prob"), (int, float)):
            return False
    return True


def load_candidates(
    paths: Sequence[Path],
    *,
    min_text_len: int = MIN_TEXT_LEN,
    exclude_samples: bool = True,
) -> tuple[list[Candidate], LoadStats]:
    """讀入 evidence 檔並過濾：只留 votes 完整者、去重 hash、去掉過短碎片。

    回傳 ``(candidates, stats)``；``candidates`` 依 ``hash`` 排序以保證決定性。
    去重「先到先留」：同 hash 跨檔也只留第一筆（檔案以排序後處理）。
    """
    stats = LoadStats()
    seen_hashes: set[str] = set()
    candidates: list[Candidate] = []

    for path in paths:
        if exclude_samples and _is_sample_path(path):
            continue
        stats.files.append(str(path))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CalibrateError(f"{path}：無法讀取檔案：{exc}") from exc
        for number, raw in enumerate(text.splitlines(), start=1):
            if not raw.strip():
                continue
            stats.seen += 1
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise CalibrateError(
                    f"{path} 第 {number} 行：JSON 解析失敗：{exc.msg}"
                ) from exc
            if not isinstance(record, dict):
                raise CalibrateError(f"{path} 第 {number} 行：每行必須是 JSON 物件")
            if not _is_scored(record):
                stats.excluded_unscored += 1
                continue
            digest = str(record.get("hash", ""))
            if not digest or digest in seen_hashes:
                stats.excluded_duplicates += 1
                continue
            seen_hashes.add(digest)
            record_text = str(record.get("text", ""))
            if len(record_text.strip()) < min_text_len:
                stats.excluded_fragments += 1
                continue
            candidates.append(
                Candidate(
                    hash=digest,
                    modelId=str(record.get("modelId", "")),
                    source=str(record.get("source", "")),
                    url=str(record.get("url", "")),
                    postedAt=str(record.get("postedAt", "")),
                    text=record_text,
                    votes={
                        qid: {
                            "label": str(record["votes"][qid]["label"]),
                            "prob": float(record["votes"][qid]["prob"]),
                        }
                        for qid in VOTE_IDS
                    },
                )
            )

    candidates.sort(key=lambda item: item.hash)
    # scored 的語意是「可抽樣候選數」＝通過去重後再扣掉碎片。
    stats.scored = len(candidates)
    return candidates, stats


# --- 分層與抽樣 -------------------------------------------------------------


def confidence_band(prob: float, threshold: float = LOW_CONFIDENCE_THRESHOLD) -> str:
    """回傳信心帶：低於門檻為 ``low``，否則 ``high``。"""
    return LOW if prob < threshold else HIGH


def band_counts(candidates: Iterable[Candidate], qid: str) -> dict[str, int]:
    """以指定面向的 ``prob`` 統計低／高信心筆數（C5 各面向分帶用該面向的 prob）。"""
    if qid not in VOTE_IDS:
        raise CalibrateError(f"未知的題目 id：{qid}（合法值：{'、'.join(VOTE_IDS)}）")
    counts = {LOW: 0, HIGH: 0}
    for candidate in candidates:
        counts[confidence_band(candidate.prob(qid))] += 1
    return counts


def _proportional(
    total: int,
    weights: dict[str, float],
    caps: dict[str, int],
    *,
    min_each: int = 0,
) -> dict[str, int]:
    """依權重把 ``total`` 個名額分給各鍵，受 ``caps`` 上限與 ``min_each`` 下限約束。

    以最大餘數法分配；權重可為小數（低信心加權就是在此放大權重）。決定性：
    平手時以鍵的字典序決定。
    """
    keys = sorted(weights)
    alloc = {key: 0 for key in keys}
    capacity = sum(caps[key] for key in keys)
    total = min(total, capacity)
    if total <= 0:
        return alloc

    remaining = total
    if min_each:
        for key in keys:
            given = min(min_each, caps[key], remaining)
            alloc[key] += given
            remaining -= given

    if remaining > 0:
        active = [key for key in keys if caps[key] - alloc[key] > 0]
        total_weight = sum(weights[key] for key in active) or 1.0
        raw = {
            key: (remaining * weights[key] / total_weight if key in active else 0.0)
            for key in keys
        }
        for key in active:
            give = min(caps[key] - alloc[key], int(raw[key]))
            alloc[key] += give
            remaining -= give
        order = sorted(keys, key=lambda key: (-(raw[key] - int(raw[key])), key))
        while remaining > 0:
            progressed = False
            for key in order:
                if remaining == 0:
                    break
                if alloc[key] < caps[key]:
                    alloc[key] += 1
                    remaining -= 1
                    progressed = True
            if not progressed:
                break

    return alloc


def _sample_stratum(
    rng: random.Random, stratum: Sequence[Candidate], count: int
) -> list[Candidate]:
    """在單一分層內以固定 seed 抽樣（候選已依 hash 排序，結果決定性）。"""
    if count <= 0:
        return []
    if count >= len(stratum):
        return list(stratum)
    return rng.sample(list(stratum), count)


def sample_candidates(
    candidates: Sequence[Candidate],
    *,
    n: int = TARGET_N,
    seed: int = SAMPLE_SEED,
    band_qid: str = OVERALL_VOTE_ID,
    low_weight: float = LOW_CONFIDENCE_WEIGHT,
    min_per_source: int = MIN_PER_SOURCE,
    threshold: float = LOW_CONFIDENCE_THRESHOLD,
) -> SampleResult:
    """分層抽樣：來源 × 信心帶，低信心帶加權 ``low_weight`` 倍。

    先依來源按候選數分名額（每來源至少 ``min_per_source``），再於來源內依
    「帶大小 × 加權」分低／高信心名額。回傳 :class:`SampleResult`，``selected``
    依 ``(source, hash)`` 排序（決定性）。
    """
    if band_qid not in VOTE_IDS:
        raise CalibrateError(f"未知的題目 id：{band_qid}（合法值：{'、'.join(VOTE_IDS)}）")
    if n < 1:
        raise CalibrateError("抽樣數 n 必須 >= 1")

    strata: dict[tuple[str, str], list[Candidate]] = {}
    for candidate in candidates:
        key = (
            candidate.source,
            confidence_band(candidate.prob(band_qid), threshold),
        )
        strata.setdefault(key, []).append(candidate)

    sources = sorted({candidate.source for candidate in candidates})
    source_sizes = {
        source: sum(len(items) for (src, _), items in strata.items() if src == source)
        for source in sources
    }
    # 每來源下限：名額夠、且每個來源都有那麼多候選才啟用。
    min_each = min_per_source
    if min_each and (n < min_each * len(sources) or any(
        size < min_each for size in source_sizes.values()
    )):
        min_each = 0

    source_alloc = _proportional(
        n, {s: float(size) for s, size in source_sizes.items()}, source_sizes,
        min_each=min_each,
    )

    rng = random.Random(seed)
    selected: list[Candidate] = []
    strata_counts: dict[str, int] = {}
    for source in sources:
        bands = {band: strata.get((source, band), []) for band in (LOW, HIGH)}
        weights = {
            band: float(len(items)) * (low_weight if band == LOW else 1.0)
            for band, items in bands.items()
        }
        caps = {band: len(items) for band, items in bands.items()}
        alloc = _proportional(source_alloc[source], weights, caps)
        for band in (LOW, HIGH):
            picked = _sample_stratum(rng, bands[band], alloc[band])
            strata_counts[f"{source}|{band}"] = len(picked)
            selected.extend(picked)

    selected.sort(key=lambda item: (item.source, item.hash))
    by_source: dict[str, int] = {}
    for candidate in selected:
        by_source[candidate.source] = by_source.get(candidate.source, 0) + 1
    return SampleResult(
        selected=selected,
        strata=strata_counts,
        by_source=dict(sorted(by_source.items())),
        seed=seed,
        band_question=band_qid,
    )


# --- 工作檔輸出 -------------------------------------------------------------


def worksheet_row(candidate: Candidate) -> dict[str, Any]:
    """把候選轉成工作檔一列：六個 gold 與標註者欄位皆為 null，**無預測欄位**。"""
    row: dict[str, Any] = {
        "hash": candidate.hash,
        "modelId": candidate.modelId,
        "source": candidate.source,
        "url": candidate.url,
        "postedAt": candidate.postedAt,
        "text": candidate.text,
    }
    for field_name in GOLD_FIELDS:
        row[field_name] = None
    row["notes"] = None
    row["annotator"] = None
    row["annotatedAt"] = None
    return row


def _atomic_write_text(path: Path, payload: str) -> None:
    """原子寫入文字檔（同目錄暫存檔、fsync 後 ``os.replace``）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        os.chmod(path, 0o644)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def write_worksheet(
    selected: Sequence[Candidate],
    output: Path,
    meta_output: Path | None = None,
    *,
    candidates: Sequence[Candidate] | None = None,
    stats: LoadStats | None = None,
    result: SampleResult | None = None,
) -> None:
    """寫出工作檔（每列一 JSON 物件）與 sidecar meta（seed、分層實抽數）。

    ``meta`` 不含時間戳，維持「同輸入同 seed 位元組相同」。
    """
    lines = [
        json.dumps(worksheet_row(candidate), ensure_ascii=False) for candidate in selected
    ]
    _atomic_write_text(output, "".join(f"{line}\n" for line in lines))

    if meta_output is None:
        return
    pool_source = candidates if candidates is not None else selected
    meta: dict[str, Any] = {
        "seed": result.seed if result else None,
        "bandQuestion": result.band_question if result else None,
        "lowConfidenceThreshold": LOW_CONFIDENCE_THRESHOLD,
        "lowConfidenceWeight": LOW_CONFIDENCE_WEIGHT,
        "target": TARGET_N,
        "cap": CAP_N,
        "minPerSource": MIN_PER_SOURCE,
        "sampled": len(selected),
        "bySource": result.by_source if result else None,
        "strata": result.strata if result else None,
        "bandByQuestion": {qid: band_counts(selected, qid) for qid in VOTE_IDS},
        "pool": {
            "files": list(stats.files) if stats else [],
            "candidates": len(pool_source),
            "excludedDuplicates": stats.excluded_duplicates if stats else None,
            "excludedFragments": stats.excluded_fragments if stats else None,
            "excludedUnscored": stats.excluded_unscored if stats else None,
        },
    }
    _atomic_write_text(
        meta_output, json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
    )


# --- 工作檔 → laya-evals gold JSONL ----------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CalibrateError(f"{path}：無法讀取檔案：{exc}") from exc
    rows: list[dict[str, Any]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CalibrateError(f"{path} 第 {number} 行：JSON 解析失敗：{exc.msg}") from exc
        if not isinstance(row, dict):
            raise CalibrateError(f"{path} 第 {number} 行：每行必須是 JSON 物件")
        rows.append(row)
    return rows


def evidence_index(paths: Sequence[Path]) -> dict[str, dict[str, Any]]:
    """建立 ``hash -> evidence record`` 索引（供 hash join；樣本目錄排除）。"""
    index: dict[str, dict[str, Any]] = {}
    for path in paths:
        if _is_sample_path(path):
            continue
        for row in _read_jsonl(path):
            digest = row.get("hash")
            if isinstance(digest, str) and digest and digest not in index:
                index[digest] = row
    return index


def _gold_value(row: dict[str, Any], qid: str) -> str | None:
    """取出單一面向的 gold；回傳 None 表示尚未標註，非法標籤丟 :class:`CalibrateError`。"""
    value = row.get(f"gold_{qid}")
    if value is None:
        return None
    if not isinstance(value, str):
        raise CalibrateError(
            f"hash={row.get('hash')} 的 gold_{qid} 必須是字串或 null，得到 {type(value).__name__}"
        )
    allowed = OVERALL_LABELS if qid == OVERALL_VOTE_ID else FACET_LABELS
    if value not in allowed:
        raise CalibrateError(
            f"hash={row.get('hash')} 的 gold_{qid}={value!r} 非法；"
            f"合法值：{'、'.join(allowed)}"
        )
    return value


def make_eval_rows(
    worksheet_path: Path,
    evidence_paths: Sequence[Path],
) -> list[dict[str, Any]]:
    """把標完的工作檔轉成 ``laya-evals`` 的 gold 資料列。

    - 以 ``hash`` join 回 evidence 取 ``text``／``source``（工作檔內容被改動時偵測得到）。
    - 六個 gold 全空的列（尚未標）跳過；部分標註的列丟 :class:`CalibrateError`（避免靜默漏標）。
    - ``questions`` 直接引用 :data:`arena.score.QUESTION`；``expected`` 六鍵；
      ``tags`` 放來源名（``laya-evals --slice tag`` 會按來源切片）；
      ``state`` 只放貼文文字，**不含模型名**（與送評一致）。
    """
    index = evidence_index(evidence_paths)
    rows = _read_jsonl(worksheet_path)
    examples: list[dict[str, Any]] = []

    for row in rows:
        digest = row.get("hash")
        if not isinstance(digest, str) or not digest:
            raise CalibrateError("工作檔有一列缺少 hash")
        golds = {qid: _gold_value(row, qid) for qid in VOTE_IDS}
        annotated = [value for value in golds.values() if value is not None]
        if not annotated:
            continue  # 尚未標註
        if len(annotated) != len(VOTE_IDS):
            missing = [qid for qid, value in golds.items() if value is None]
            raise CalibrateError(
                f"hash={digest} 只標了部分面向（缺：{'、'.join(missing)}）；"
                "每筆要嘛六個面向全標、要嘛全空"
            )
        record = index.get(digest)
        if record is None:
            raise CalibrateError(f"hash={digest} 在 evidence 找不到（無法 join 回原文）")
        source = str(record.get("source") or row.get("source") or "")
        if not source:
            raise CalibrateError(f"hash={digest} 取不到來源，無法設 tags")
        examples.append(
            {
                "state": {"post": str(record.get("text", ""))},
                "questions": QUESTION,
                "expected": dict(golds),
                "tags": [source],
                "language": "en",
            }
        )
    return examples


def write_evals(examples: Sequence[dict[str, Any]], output: Path) -> None:
    """把 gold 資料列寫成 JSONL（每行一個物件，laya-evals 可直接吃）。"""
    lines = [json.dumps(row, ensure_ascii=False) for row in examples]
    _atomic_write_text(output, "".join(f"{line}\n" for line in lines))


# --- 標註進度 ---------------------------------------------------------------


def annotation_stats(worksheet_path: Path) -> dict[str, Any]:
    """統計工作檔的標註進度（總數、完成、部分、未標）與各面向非空數。"""
    rows = _read_jsonl(worksheet_path)
    complete = partial = pending = 0
    per_facet: dict[str, int] = {qid: 0 for qid in VOTE_IDS}
    for row in rows:
        values = [row.get(f"gold_{qid}") for qid in VOTE_IDS]
        counts = sum(1 for value in values if value is not None)
        if counts == 0:
            pending += 1
        elif counts == len(VOTE_IDS):
            complete += 1
        else:
            partial += 1
        for qid in VOTE_IDS:
            if row.get(f"gold_{qid}") is not None:
                per_facet[qid] += 1
    return {
        "total": len(rows),
        "complete": complete,
        "partial": partial,
        "pending": pending,
        "perQuestion": per_facet,
    }


# --- CLI -------------------------------------------------------------------


def _resolve_inputs(inputs: Sequence[str] | None, default: str) -> list[Path]:
    patterns = list(inputs) if inputs else [default]
    files: list[Path] = []
    for pattern in patterns:
        if any(char in pattern for char in "*?["):
            files.extend(sorted(Path().glob(pattern)))
        else:
            files.append(Path(pattern))
    return sorted(set(files))


def run_sample(args: argparse.Namespace) -> int:
    paths = _resolve_inputs(getattr(args, "inputs", None), DEFAULT_EVIDENCE_GLOB)
    if not paths:
        print(f"arena calibrate sample：找不到 evidence 檔（{DEFAULT_EVIDENCE_GLOB}）。", file=sys.stderr)
        return EXIT_ERROR
    output = Path(getattr(args, "output", DEFAULT_WORKSHEET))
    meta_output = Path(
        getattr(args, "meta_output", None) or (str(output) + ".meta.json")
    )

    try:
        candidates, stats = load_candidates(paths)
        if not candidates:
            print("arena calibrate sample：過濾後沒有可抽樣的資料。", file=sys.stderr)
            return EXIT_ERROR
        n = int(getattr(args, "n", TARGET_N))
        n = max(1, min(n, CAP_N))
        result = sample_candidates(
            candidates,
            n=n,
            seed=int(getattr(args, "seed", SAMPLE_SEED)),
            band_qid=getattr(args, "band_question", OVERALL_VOTE_ID),
            low_weight=float(getattr(args, "low_weight", LOW_CONFIDENCE_WEIGHT)),
        )
        write_worksheet(
            result.selected,
            output,
            meta_output,
            candidates=candidates,
            stats=stats,
            result=result,
        )
    except CalibrateError as exc:
        print(f"arena calibrate sample：{exc}", file=sys.stderr)
        return EXIT_ERROR

    print(
        f"arena calibrate sample：池 {stats.candidates} 筆（讀 {stats.seen}、"
        f"去重 {stats.excluded_duplicates}、碎片 {stats.excluded_fragments}、"
        f"未評分 {stats.excluded_unscored}），實抽 {len(result.selected)} 筆。"
    )
    print(f"  分層以 {result.band_question} 的 prob 分帶（<{LOW_CONFIDENCE_THRESHOLD} 加權 {LOW_CONFIDENCE_WEIGHT}x）")
    for key in sorted(result.strata):
        print(f"  {key}: {result.strata[key]}")
    print(f"  工作表：{output}")
    print(f"  中繼資料：{meta_output}")
    return EXIT_OK


def run_make_evals(args: argparse.Namespace) -> int:
    worksheet = Path(getattr(args, "worksheet", DEFAULT_WORKSHEET))
    if not worksheet.exists():
        print(f"arena calibrate make-evals：找不到工作檔 {worksheet}", file=sys.stderr)
        return EXIT_ERROR
    paths = _resolve_inputs(getattr(args, "inputs", None), DEFAULT_EVIDENCE_GLOB)
    output = Path(getattr(args, "output", DEFAULT_GOLD))
    try:
        examples = make_eval_rows(worksheet, paths)
        if not examples:
            print("arena calibrate make-evals：工作檔還沒有任何已標註的列。", file=sys.stderr)
            return EXIT_ERROR
        write_evals(examples, output)
    except CalibrateError as exc:
        print(f"arena calibrate make-evals：{exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"arena calibrate make-evals：輸出 {len(examples)} 筆 gold → {output}")
    return EXIT_OK


def run_stats(args: argparse.Namespace) -> int:
    worksheet = Path(getattr(args, "worksheet", DEFAULT_WORKSHEET))
    if not worksheet.exists():
        print(f"arena calibrate stats：找不到工作檔 {worksheet}", file=sys.stderr)
        return EXIT_ERROR
    try:
        stats = annotation_stats(worksheet)
    except CalibrateError as exc:
        print(f"arena calibrate stats：{exc}", file=sys.stderr)
        return EXIT_ERROR
    print(
        f"arena calibrate stats：{stats['total']} 筆（完成 {stats['complete']}、"
        f"部分 {stats['partial']}、未標 {stats['pending']}）"
    )
    for qid in VOTE_IDS:
        print(f"  {qid}: {stats['perQuestion'][qid]}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arena calibrate",
        description="C5 人工標註：分層抽樣工作檔與 laya-evals gold 轉換（見 docs/annotation-guide.md）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sample = sub.add_parser("sample", help="由 evidence 抽出人工標註工作檔")
    sample.add_argument("--input", dest="inputs", nargs="*", help=f"evidence 檔或 glob（預設 {DEFAULT_EVIDENCE_GLOB}）")
    sample.add_argument("--output", default=DEFAULT_WORKSHEET, help="工作檔輸出路徑")
    sample.add_argument("--meta-output", default=None, help="中繼資料輸出路徑（預設 <output>.meta.json）")
    sample.add_argument("--n", type=int, default=TARGET_N, help=f"抽樣數（預設 {TARGET_N}，上限 {CAP_N}）")
    sample.add_argument("--seed", type=int, default=SAMPLE_SEED, help=f"亂數種子（預設 {SAMPLE_SEED}）")
    sample.add_argument("--band-question", default=OVERALL_VOTE_ID, help="分帶用的題目 id（預設 overall）")
    sample.add_argument("--low-weight", type=float, default=LOW_CONFIDENCE_WEIGHT, help="低信心帶加權倍數（預設 2.5）")
    sample.set_defaults(func=run_sample)

    evals = sub.add_parser("make-evals", help="標完的工作檔轉成 laya-evals gold JSONL")
    evals.add_argument("worksheet", nargs="?", default=DEFAULT_WORKSHEET, help="標註工作檔")
    evals.add_argument("--input", dest="inputs", nargs="*", help=f"evidence 檔或 glob（預設 {DEFAULT_EVIDENCE_GLOB}）")
    evals.add_argument("--output", default=DEFAULT_GOLD, help=f"gold JSONL 輸出路徑（預設 {DEFAULT_GOLD}）")
    evals.set_defaults(func=run_make_evals)

    stats = sub.add_parser("stats", help="顯示工作檔的標註進度")
    stats.add_argument("worksheet", nargs="?", default=DEFAULT_WORKSHEET, help="標註工作檔")
    stats.set_defaults(func=run_stats)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - 由 python -m arena.calibrate 觸發
    raise SystemExit(main())


__all__ = [
    "CAP_N",
    "CalibrateError",
    "Candidate",
    "DEFAULT_EVIDENCE_GLOB",
    "DEFAULT_GOLD",
    "DEFAULT_WORKSHEET",
    "GOLD_FIELDS",
    "HIGH",
    "LOW",
    "LOW_CONFIDENCE_THRESHOLD",
    "LOW_CONFIDENCE_WEIGHT",
    "LoadStats",
    "MIN_N",
    "MIN_PER_SOURCE",
    "MIN_TEXT_LEN",
    "SAMPLE_SEED",
    "SampleResult",
    "TARGET_N",
    "WORKSHEET_FIELDS",
    "annotation_stats",
    "band_counts",
    "build_parser",
    "confidence_band",
    "evidence_index",
    "load_candidates",
    "main",
    "make_eval_rows",
    "run_make_evals",
    "run_sample",
    "run_stats",
    "sample_candidates",
    "worksheet_row",
    "write_evals",
    "write_worksheet",
]
