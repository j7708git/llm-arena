"""`arena build` 的測試（任務 C4）：全離線，用小型手工 evidence fixture。

驗證重點（對應 docs/plan.md 實作裁定第 10 條與任務卡驗收）：

- P／N／null 判定與 ``dimensionSamples``。
- K=10 偽樣本數收縮的數值可手算（n=10、全正 → 75.0）。
- 全無某面向討論 → 該面向 ``null``，總分只以非 null 面向重歸一。
- Wilson 95% 下界的 sampleSize=0 → 0 與一般值（scipy-free 手算對照）。
- 未評分列跳過並在 stderr 報數；零樣本模型被排除且列進 meta.notes。
- 產出通過 ``arena validate``、重跑（除時間戳外）逐位元組相同、原子寫入不留半檔。
"""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from arena import build
from arena.build import (
    build_document,
    dimension_score,
    run,
    wilson_lower_bound,
)
from arena.cli import main
from arena.schema import FACET_DIMENSION_IDS, OVERALL_VOTE_ID
from arena.validate import validate_path

# evidence 檔實際寫的 judge 是 llm-jury@<hash>（C8 起）；舊 laya judge 一律不算。
SHORT_JUDGE = build.JURY_JUDGE_ID
FULL_JUDGE = build.JURY_JUDGE_ID
FACETS = FACET_DIMENSION_IDS


# --- fixture 工具 -----------------------------------------------------------


def _votes(overall: str = "neutral", **facets: str) -> dict:
    """組出六鍵 votes；未指定的面向一律 ``not-discussed``。"""
    votes = {OVERALL_VOTE_ID: {"label": overall, "prob": 0.5}}
    for facet in FACETS:
        votes[facet] = {"label": facets.get(facet, "not-discussed"), "prob": 0.5}
    return votes


def _record(
    model_id: str,
    *,
    source: str = "reddit",
    votes: dict | None = None,
    judge: str | None = SHORT_JUDGE,
    text: str = "a post",
) -> dict:
    return {
        "hash": "h",
        "modelId": model_id,
        "source": source,
        "url": "https://example.com/post",
        "author": None,
        "postedAt": "2026-09-24T00:00:00Z",
        "text": text,
        "votes": votes,
        "judge": judge,
    }


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _models(*ids: str) -> dict[str, dict]:
    return {
        model_id: {
            "id": model_id,
            "name": f"Name {model_id}",
            "provider": "Prov",
            "priceUsdPerMTok": {"in": 1.0, "out": 2.0},
        }
        for model_id in ids
    }


def _entry(document: dict, model_id: str) -> dict:
    for entry in document["models"]:
        if entry["id"] == model_id:
            return entry
    raise AssertionError(f"{model_id} 不在榜上：{document['models']}")


# --- 公式本身 ---------------------------------------------------------------


def test_dimension_score_hand_values() -> None:
    # n=10、全正：50*2*10/20 + 50*10/20 = 75.0（任務卡點名的手算例子）。
    assert dimension_score(10, 0) == 75.0
    # n=10、全負。
    assert dimension_score(0, 10) == 25.0
    # n=1 的收縮：50 + 50*1*1/11 = 54.545... → 54.5。
    assert dimension_score(1, 0) == 54.5
    assert dimension_score(0, 1) == 45.5
    # n=0 → 沒有表態，資料不足，回 None（不得當成 50）。
    assert dimension_score(0, 0) is None


def test_dimension_score_shrinks_toward_50() -> None:
    # 同樣全正，樣本越大越接近 100。
    assert dimension_score(1, 0) < dimension_score(10, 0) < dimension_score(90, 0)
    # n=90、全正：50 + 50*1*90/100 = 95.0（收 10%）。
    assert dimension_score(90, 0) == 95.0
    # 正負相抵 → 剛好 50。
    assert dimension_score(3, 3) == 50.0


def test_wilson_lower_bound_hand_values() -> None:
    assert wilson_lower_bound(0, 0) == 0.0

    def hand(positive: int, sample_size: int) -> float:
        z = build.WILSON_Z
        n = sample_size
        p = positive / n
        return (p + z * z / (2 * n) - z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)) / (
            1 + z * z / n
        )

    assert wilson_lower_bound(5, 10) == pytest.approx(hand(5, 10))
    assert wilson_lower_bound(3, 10) == pytest.approx(hand(3, 10))
    # n=10、全正 → 1 / 1.38416 ≈ 0.72246。
    assert wilson_lower_bound(10, 10) == pytest.approx(0.72246, abs=1e-4)


# --- 聚合 -------------------------------------------------------------------


def test_aggregation_pn_null_and_samples(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "e.jsonl",
        [
            _record("m/a", source="reddit", votes=_votes("neutral", quality="positive")),
            _record("m/a", source="hn", votes=_votes("positive", quality="negative")),
            _record("m/a", source="reddit", votes=_votes("negative", quality="positive")),
        ],
    )
    rows = build._load_rows([path])
    document, unscored, mismatched = build_document(rows, _models("m/a"))

    assert (unscored, mismatched) == (0, 0)
    entry = _entry(document, "m/a")
    # quality：P=2、N=1、n=3 → 手算 raw=1/3。
    assert entry["dimensionSamples"]["quality"] == 3
    assert entry["dimensions"]["quality"] == dimension_score(2, 1)
    # 其餘面向全 not-discussed → n=0 → null。
    for facet in ("speed", "tokenEfficiency", "tokenUsage", "priceValue"):
        assert entry["dimensions"][facet] is None
        assert entry["dimensionSamples"][facet] == 0
    assert entry["sampleSize"] == 3
    # overall：1 個 positive、2 個 neutral/negative → 正面率 1/3。
    assert entry["positiveRate"] == pytest.approx(1 / 3)
    assert entry["confidence"] == pytest.approx(wilson_lower_bound(1, 3))
    assert entry["mentionsBySource"] == {"hn": 1, "reddit": 2}
    assert entry["id"] == "m/a" and entry["name"] == "Name m/a"
    assert entry["priceUsdPerMTok"] == {"in": 1.0, "out": 2.0}
    assert entry["updatedAt"] == document["meta"]["generatedAt"]


def test_score_renormalizes_after_null_facets(tmp_path: Path) -> None:
    """只有 quality 與 priceValue 有表態時，總分只用這兩個面向重歸一。"""
    records = [
        _record("m/a", votes=_votes("neutral", quality="positive", priceValue="positive")),
        _record("m/a", votes=_votes("neutral", quality="positive", priceValue="positive")),
    ]
    records += [
        _record("m/a", votes=_votes("neutral", quality="positive")) for _ in range(8)
    ]
    path = _write(tmp_path / "e.jsonl", records)
    document, _, _ = build_document(build._load_rows([path]), _models("m/a"))
    entry = _entry(document, "m/a")

    assert entry["dimensions"]["quality"] == 75.0  # n=10 全正
    assert entry["dimensions"]["priceValue"] == dimension_score(2, 0)  # n=2 全正
    for facet in ("speed", "tokenEfficiency", "tokenUsage"):
        assert entry["dimensions"][facet] is None

    weights = document["meta"]["weights"]
    expected = round(
        (weights["quality"] * 75.0 + weights["priceValue"] * dimension_score(2, 0))
        / (weights["quality"] + weights["priceValue"]),
        1,
    )
    assert entry["score"] == expected
    # 若沒有重歸一（把 null 當 0），分數會明顯不同——確認真的重歸一了。
    assert entry["score"] != round(
        weights["quality"] * 75.0 + weights["priceValue"] * dimension_score(2, 0), 1
    )


def test_k_shrinkage_n10_all_positive_is_75(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "e.jsonl",
        [_record("m/a", votes=_votes("positive", quality="positive")) for _ in range(10)],
    )
    document, _, _ = build_document(build._load_rows([path]), _models("m/a"))
    entry = _entry(document, "m/a")

    assert entry["dimensions"]["quality"] == 75.0
    assert entry["dimensionSamples"]["quality"] == 10
    # 只有 quality 有資料 → 總分就是 quality 分數。
    assert entry["score"] == 75.0
    assert entry["positiveRate"] == 1.0


# --- 未評分、零樣本、judge 不符 ---------------------------------------------


def test_unscored_rows_skipped_and_counted(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "e.jsonl",
        [
            _record("m/a", votes=_votes("positive", quality="positive")),
            _record("m/a", votes=None, judge=None),
            _record("m/a", votes=None, judge=None),
        ],
    )
    document, unscored, mismatched = build_document(
        build._load_rows([path]), _models("m/a")
    )

    assert (unscored, mismatched) == (2, 0)
    entry = _entry(document, "m/a")
    assert entry["sampleSize"] == 1
    assert entry["mentionsBySource"] == {"reddit": 1}
    # evidence 參照包含「全部」該模型的列（含未評分者）。
    assert entry["evidence"] == [
        "evidence/e.jsonl#l1",
        "evidence/e.jsonl#l2",
        "evidence/e.jsonl#l3",
    ]


def test_run_reports_unscored_count_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    _write(
        evidence_dir / "2026-09-29.jsonl",
        [
            _record("m/a", votes=_votes("positive", quality="positive")),
            _record("m/a", votes=None, judge=None),
        ],
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(build, "DEFAULT_EVIDENCE_GLOB", "evidence/*.jsonl")
    monkeypatch.setattr(build, "DEFAULT_MODELS", tmp_path / "models.json")
    out = tmp_path / "scores.json"

    assert run(Namespace(window_days=30, output=out)) == build.EXIT_OK

    assert "跳過 1 筆未評分" in capsys.readouterr().err
    assert validate_path(out) == []


def test_judge_mismatch_rows_are_skipped(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "e.jsonl",
        [
            _record("m/a", votes=_votes("positive", quality="positive")),
            _record("m/a", votes=_votes("positive", quality="positive"), judge="laya@deadbeef"),
            _record("m/a", votes=_votes("positive", quality="positive"), judge=FULL_JUDGE),
        ],
    )
    document, unscored, mismatched = build_document(
        build._load_rows([path]), _models("m/a")
    )

    assert (unscored, mismatched) == (0, 1)
    # 短 sha 與完整 sha 都算同一個評分器，所以計入 2 列。
    assert _entry(document, "m/a")["sampleSize"] == 2


def test_zero_sample_models_excluded_and_listed_in_notes(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "e.jsonl",
        [
            _record("m/a", votes=_votes("positive", quality="positive")),
            # m/b 只有未評分的列 → sampleSize=0。
            _record("m/b", votes=None, judge=None),
        ],
    )
    document, _, _ = build_document(
        build._load_rows([path]), _models("m/a", "m/b", "m/never-seen")
    )

    ids = [entry["id"] for entry in document["models"]]
    assert ids == ["m/a"]
    notes = document["meta"]["notes"]
    assert "m/b" in notes
    assert "m/never-seen" in notes
    assert "m/a" not in notes.split("未列入榜")[1]


# --- 輸出：validate、決定性、原子寫入 ---------------------------------------


def _fixture_rows(tmp_path: Path) -> list[build.EvidenceRow]:
    path = _write(
        tmp_path / "evidence.jsonl",
        [
            _record("m/a", source="reddit", votes=_votes("positive", quality="positive")),
            _record("m/a", source="hn", votes=_votes("negative", speed="negative")),
        ],
    )
    return build._load_rows([path])


def test_written_output_passes_validate(tmp_path: Path) -> None:
    document, _, _ = build_document(_fixture_rows(tmp_path), _models("m/a"))
    out = tmp_path / "scores.json"

    assert build._write_document(out, document) == []
    assert validate_path(out) == []
    assert main(["validate", str(out)]) == 0


def test_rerun_is_byte_identical_except_timestamps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = _fixture_rows(tmp_path)
    # 兩次用不同的「現在」時間，輸出的其餘位元組必須完全相同。
    times = iter(["2000-01-01T00:00:00Z", "2001-02-03T04:05:06Z"])
    monkeypatch.setattr(build, "_utcnow_iso", lambda: next(times))

    first, second = tmp_path / "a.json", tmp_path / "b.json"
    document_a, _, _ = build_document(rows, _models("m/a"))
    assert build._write_document(first, document_a) == []
    document_b, _, _ = build_document(rows, _models("m/a"))
    assert build._write_document(second, document_b) == []

    bytes_a = first.read_bytes().replace(b"2000-01-01T00:00:00Z", b"<TS>")
    bytes_b = second.read_bytes().replace(b"2001-02-03T04:05:06Z", b"<TS>")
    assert bytes_a == bytes_b


def test_validation_failure_keeps_original_and_removes_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "scores.json"
    out.write_text("原檔不能動", encoding="utf-8")
    monkeypatch.setattr(build, "validate_path", lambda _path: ["故意讓驗證失敗"])

    errors = build._write_document(out, {"meta": {}, "models": []})

    assert errors == ["故意讓驗證失敗"]
    assert out.read_text(encoding="utf-8") == "原檔不能動"
    # 不留下暫存檔。
    assert sorted(item.name for item in tmp_path.iterdir()) == ["scores.json"]


def test_successful_write_leaves_no_temp_file(tmp_path: Path) -> None:
    document, _, _ = build_document(_fixture_rows(tmp_path), _models("m/a"))
    out = tmp_path / "scores.json"

    assert build._write_document(out, document) == []
    assert sorted(item.name for item in tmp_path.iterdir()) == ["evidence.jsonl", "scores.json"]


# --- CLI --------------------------------------------------------------------


def test_cli_build_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    _write(
        evidence_dir / "2026-09-29.jsonl",
        [_record("m/a", votes=_votes("positive", quality="positive"))],
    )
    models_path = tmp_path / "models.json"
    models_path.write_text(
        json.dumps({"meta": {}, "models": list(_models("m/a").values())}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(build, "DEFAULT_EVIDENCE_GLOB", "evidence/*.jsonl")
    monkeypatch.setattr(build, "DEFAULT_MODELS", models_path)
    out = tmp_path / "scores.json"

    assert main(["build", "--window-days", "7", "--output", str(out)]) == 0

    captured = capsys.readouterr()
    assert "已寫入" in captured.out
    assert f"m/a: {dimension_score(1, 0)}" in captured.out
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["meta"]["windowDays"] == 7
    assert validate_path(out) == []


def test_add_arguments_exposes_only_window_days_and_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arena.cli import build_parser

    parser = build_parser()
    namespace = parser.parse_args(["build"])

    assert namespace.window_days == build.DEFAULT_WINDOW_DAYS
    assert namespace.output == build.DEFAULT_OUTPUT
    assert not hasattr(namespace, "files")


def test_window_days_below_one_is_rejected(tmp_path: Path) -> None:
    out = tmp_path / "scores.json"
    assert run(Namespace(window_days=0, output=out)) == build.EXIT_ERROR
    assert not out.exists()
