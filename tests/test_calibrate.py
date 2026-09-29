"""`arena calibrate` 的離線測試（任務 C5a）。

全部測試都不載入模型、不連網：抽樣用構造的 evidence fixture；``make-evals``
只用 ``laya.evals`` 的 schema（torch-free 的 ``Dataset.from_jsonl``）驗結構，
laya 未安裝時退回純 JSON 結構檢查（C5 的評測本身不需在此跑）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arena import calibrate as cal
from arena.schema import VOTE_IDS
from arena.score import QUESTION

OVERALL = "overall"


# --- fixture 工具 -----------------------------------------------------------


def make_record(
    digest: str,
    source: str = "reddit",
    *,
    overall_prob: float = 0.9,
    overall_label: str = "positive",
    facet_prob: float | None = None,
    text: str | None = None,
) -> dict:
    """組一筆 votes 完整的 evidence 列。"""
    facet_prob = overall_prob if facet_prob is None else facet_prob
    votes = {
        OVERALL: {"label": overall_label, "prob": overall_prob},
    }
    for qid in VOTE_IDS:
        if qid == OVERALL:
            continue
        votes[qid] = {"label": "not-discussed", "prob": facet_prob}
    return {
        "hash": digest,
        "modelId": "anthropic/claude-sonnet-4",
        "source": source,
        "url": f"https://example.com/{digest}",
        "author": None,
        "postedAt": "2026-09-27T00:00:00Z",
        "text": text or f"a meaningful post body about a model ({digest})",
        "votes": votes,
        "judge": "laya@55cf4c4",
    }


def write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
        encoding="utf-8",
    )
    return path


def load_ws(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def candidates_of(records: list[dict]) -> list[cal.Candidate]:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = write_jsonl(Path(tmp) / "evidence.jsonl", records)
        candidates, _ = cal.load_candidates([path])
    return candidates


# --- 信心帶 -----------------------------------------------------------------


def test_confidence_band_boundary() -> None:
    assert cal.confidence_band(0.6999) == cal.LOW
    assert cal.confidence_band(0.70) == cal.HIGH  # 門檻本身算高信心
    assert cal.confidence_band(0.0) == cal.LOW
    assert cal.confidence_band(1.0) == cal.HIGH


def test_band_counts_uses_that_question_prob() -> None:
    record = make_record("a", overall_prob=0.95, facet_prob=0.50)
    candidate = candidates_of([record])[0]
    assert cal.band_counts([candidate], OVERALL) == {cal.LOW: 0, cal.HIGH: 1}
    assert cal.band_counts([candidate], "quality") == {cal.LOW: 1, cal.HIGH: 0}


# --- 載入與過濾 -------------------------------------------------------------


def test_load_filters_duplicates_fragments_and_unscored(tmp_path: Path) -> None:
    records = [
        make_record("keep-1", "reddit"),
        make_record("keep-2", "hn"),
        make_record("keep-1", "x"),  # 重複 hash → 只留第一筆
        make_record("frag", "reddit", text="too short"),  # <10 字 → 丟
        {**make_record("unscored", "reddit"), "votes": None, "judge": None},
    ]
    path = write_jsonl(tmp_path / "e.jsonl", records)
    candidates, stats = cal.load_candidates([path])

    assert [c.hash for c in candidates] == ["keep-1", "keep-2"]
    assert stats.seen == 5
    assert stats.candidates == 2
    assert stats.excluded_duplicates == 1
    assert stats.excluded_fragments == 1
    assert stats.excluded_unscored == 1


def test_load_excludes_samples_directory(tmp_path: Path) -> None:
    path = write_jsonl(tmp_path / "samples" / "evidence.sample.jsonl", [make_record("s1")])
    candidates, stats = cal.load_candidates([path])
    assert candidates == []
    assert stats.files == []


# --- 抽樣決定性與加權 -------------------------------------------------------


def _pool(size_per_source: int = 30) -> list[dict]:
    records: list[dict] = []
    for source in ("reddit", "hn", "x"):
        for index in range(size_per_source):
            prob = 0.4 if index % 3 == 0 else 0.92  # 約 1/3 低信心
            records.append(make_record(f"{source}-{index:03d}", source, overall_prob=prob))
    return records


def test_sampling_is_deterministic() -> None:
    candidates = candidates_of(_pool())
    first = cal.sample_candidates(candidates, n=45, seed=123)
    second = cal.sample_candidates(candidates, n=45, seed=123)
    assert [c.hash for c in first.selected] == [c.hash for c in second.selected]
    assert first.strata == second.strata

    other = cal.sample_candidates(candidates, n=45, seed=999)
    # 不同 seed 幾乎一定會抽到不同清單（碰撞機率極低，取 45/90）。
    assert [c.hash for c in other.selected] != [c.hash for c in first.selected]


def test_sampling_order_is_source_then_hash() -> None:
    result = cal.sample_candidates(candidates_of(_pool()), n=45, seed=7)
    keys = [(c.source, c.hash) for c in result.selected]
    assert keys == sorted(keys)


def test_low_confidence_oversampled() -> None:
    records = [
        make_record(f"low-{i:03d}", "reddit", overall_prob=0.30) for i in range(10)
    ] + [
        make_record(f"high-{i:03d}", "reddit", overall_prob=0.95) for i in range(90)
    ]
    candidates = candidates_of(records)

    unweighted = cal.sample_candidates(
        candidates, n=20, seed=5, low_weight=1.0, min_per_source=0
    )
    weighted = cal.sample_candidates(
        candidates, n=20, seed=5, low_weight=2.5, min_per_source=0
    )
    low_unweighted = unweighted.strata["reddit|low"]
    low_weighted = weighted.strata["reddit|low"]

    # 無加權時低信心只按 10/100 比例拿到 2 筆；加權 2.5 倍必須抽更多。
    assert low_unweighted == 2
    assert low_weighted > low_unweighted
    assert low_weighted >= 3


def test_sample_respects_min_per_source_and_target() -> None:
    result = cal.sample_candidates(candidates_of(_pool(size_per_source=60)), n=150, seed=1)
    assert len(result.selected) == 150
    assert set(result.by_source) == {"reddit", "hn", "x"}
    assert all(count >= cal.MIN_PER_SOURCE for count in result.by_source.values())


def test_sample_when_pool_smaller_than_target() -> None:
    candidates = candidates_of(
        [make_record(f"only-{i:02d}", "reddit") for i in range(8)]
    )
    result = cal.sample_candidates(candidates, n=150, seed=1)
    assert len(result.selected) == 8


# --- 工作檔 -----------------------------------------------------------------


def test_worksheet_has_no_prediction_fields(tmp_path: Path) -> None:
    path = write_jsonl(tmp_path / "e.jsonl", _pool(size_per_source=20))
    output = tmp_path / "worksheet.jsonl"
    exit_code = cal.main(
        ["sample", "--input", str(path), "--output", str(output), "--n", "30"]
    )
    assert exit_code == cal.EXIT_OK

    raw = output.read_text(encoding="utf-8")
    rows = load_ws(output)
    assert len(rows) == 30

    for row in rows:
        assert tuple(row) == cal.WORKSHEET_FIELDS
        for field_name in cal.GOLD_FIELDS:
            assert row[field_name] is None
        # 防 anchoring 回歸：任何預測欄位名（label／prob）都不得出現。
        for key in row:
            lowered = key.lower()
            assert "label" not in lowered and "prob" not in lowered, key
    # 連原始文字也不得夾帶預測欄位。
    assert '"label"' not in raw
    assert '"prob"' not in raw

    meta = json.loads((tmp_path / "worksheet.jsonl.meta.json").read_text(encoding="utf-8"))
    assert meta["seed"] == cal.SAMPLE_SEED
    assert meta["sampled"] == 30
    assert set(meta["bandByQuestion"]) == set(VOTE_IDS)


def test_sample_output_is_byte_identical_on_rerun(tmp_path: Path) -> None:
    path = write_jsonl(tmp_path / "e.jsonl", _pool(size_per_source=20))
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    cal.main(["sample", "--input", str(path), "--output", str(first), "--n", "40"])
    cal.main(["sample", "--input", str(path), "--output", str(second), "--n", "40"])
    assert first.read_bytes() == second.read_bytes()
    assert (
        (tmp_path / "a.jsonl.meta.json").read_bytes()
        == (tmp_path / "b.jsonl.meta.json").read_bytes()
    )


# --- make-evals -------------------------------------------------------------


def _annotated_worksheet(tmp_path: Path) -> tuple[Path, Path]:
    """回傳 (evidence_path, worksheet_path)：worksheet 有 2 筆標完、1 筆未標。"""
    records = [
        make_record("done-1", "reddit"),
        make_record("done-2", "hn"),
        make_record("pending-1", "x"),
    ]
    evidence = write_jsonl(tmp_path / "e.jsonl", records)

    rows = []
    for record in records[:2]:
        row = cal.worksheet_row(candidates_of([record])[0])
        row["gold_overall"] = "positive"
        row["gold_quality"] = "positive"
        row["gold_speed"] = "not-discussed"
        row["gold_tokenEfficiency"] = "not-discussed"
        row["gold_tokenUsage"] = "not-discussed"
        row["gold_priceValue"] = "negative"
        row["notes"] = "fixture"
        row["annotator"] = "tester"
        row["annotatedAt"] = "2026-09-29T00:00:00Z"
        rows.append(row)
    pending = cal.worksheet_row(candidates_of([records[2]])[0])
    rows.append(pending)
    worksheet = write_jsonl(tmp_path / "worksheet.jsonl", rows)
    return evidence, worksheet


def test_make_evals_output_schema(tmp_path: Path) -> None:
    evidence, worksheet = _annotated_worksheet(tmp_path)
    output = tmp_path / "gold.jsonl"
    exit_code = cal.main(
        ["make-evals", str(worksheet), "--input", str(evidence), "--output", str(output)]
    )
    assert exit_code == cal.EXIT_OK

    rows = load_ws(output)
    assert len(rows) == 2  # 未標的那筆被跳過
    for row in rows:
        assert set(row) == {"state", "questions", "expected", "tags", "language"}
        assert row["questions"] == QUESTION  # JSON 序列化後比對
        assert set(row["expected"]) == set(VOTE_IDS)
        assert row["tags"] in (["reddit"], ["hn"])
        assert row["language"] == "en"
        assert "post" in row["state"]

    # questions 直接引用 score.QUESTION 的同一個物件（不複製貼上，防 rubric 漂移）。
    direct = cal.make_eval_rows(worksheet, [evidence])
    assert all(row["questions"] is QUESTION for row in direct)

    # 若裝了 laya，用它的 schema 真正解析一次（torch-free）。
    laya_evals = pytest.importorskip("laya.evals", reason="laya 未安裝，略過 schema 解析")
    dataset = laya_evals.Dataset.from_jsonl(str(output))
    assert len(dataset) == 2
    assert set(dataset.examples[0].expected) == set(VOTE_IDS)


def test_make_evals_partial_annotation_raises(tmp_path: Path) -> None:
    evidence, worksheet = _annotated_worksheet(tmp_path)
    rows = load_ws(worksheet)
    rows[0]["gold_speed"] = None  # 部分標註
    write_jsonl(worksheet, rows)
    with pytest.raises(cal.CalibrateError, match="部分面向"):
        cal.make_eval_rows(worksheet, [evidence])


def test_make_evals_invalid_label_raises(tmp_path: Path) -> None:
    evidence, worksheet = _annotated_worksheet(tmp_path)
    rows = load_ws(worksheet)
    rows[0]["gold_overall"] = "neutral"  # overall 可以用 neutral
    rows[0]["gold_speed"] = "neutral"  # 面向不允許 neutral
    write_jsonl(worksheet, rows)
    with pytest.raises(cal.CalibrateError, match="非法"):
        cal.make_eval_rows(worksheet, [evidence])


def test_make_evals_missing_evidence_hash_raises(tmp_path: Path) -> None:
    _, worksheet = _annotated_worksheet(tmp_path)
    empty_evidence = write_jsonl(tmp_path / "other.jsonl", [make_record("unrelated")])
    with pytest.raises(cal.CalibrateError, match="找不到"):
        cal.make_eval_rows(worksheet, [empty_evidence])


def test_make_evals_no_annotations_returns_error(tmp_path: Path) -> None:
    records = [make_record("pending-1")]
    evidence = write_jsonl(tmp_path / "e.jsonl", records)
    worksheet = write_jsonl(
        tmp_path / "worksheet.jsonl", [cal.worksheet_row(candidates_of(records)[0])]
    )
    output = tmp_path / "gold.jsonl"
    exit_code = cal.main(
        ["make-evals", str(worksheet), "--input", str(evidence), "--output", str(output)]
    )
    assert exit_code == cal.EXIT_ERROR
    assert not output.exists()


# --- stats ------------------------------------------------------------------


def test_annotation_stats(tmp_path: Path) -> None:
    evidence, worksheet = _annotated_worksheet(tmp_path)
    stats = cal.annotation_stats(worksheet)
    assert stats["total"] == 3
    assert stats["complete"] == 2
    assert stats["partial"] == 0
    assert stats["pending"] == 1
    assert stats["perQuestion"][OVERALL] == 2

    exit_code = cal.main(["stats", str(worksheet)])
    assert exit_code == cal.EXIT_OK
