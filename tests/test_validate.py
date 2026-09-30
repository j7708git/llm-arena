"""`arena validate` 的測試：合法種子通過、各種改壞的檔要被擋下並指出欄位。

壞檔一律寫到 pytest 的 tmp_path，不留在 repo 裡。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from arena.cli import main
from arena.schema import (
    FACET_DIMENSION_IDS,
    JURY_SCHEMA_VERSION,
    VOTE_IDS,
    EvidenceRecord,
    EvidenceRecordV12,
    ScoresDocument,
)
from arena.validate import validate_path

ROOT = Path(__file__).resolve().parents[1]
SEED_SCORES = ROOT / "data" / "scores.json"
SEED_EVIDENCE = ROOT / "data" / "samples" / "evidence.sample.jsonl"
REAL_EVIDENCE = ROOT / "data" / "evidence" / "2026-09-29.jsonl"


def load_seed_scores() -> dict:
    return json.loads(SEED_SCORES.read_text(encoding="utf-8"))


def write_json(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_broken_scores(tmp_path: Path, mutate) -> Path:
    data = copy.deepcopy(load_seed_scores())
    mutate(data)
    return write_json(tmp_path / "scores.json", data)


def _valid_votes() -> dict:
    """一組合法的六鍵 votes（overall + 五面向）。"""
    votes = {"overall": {"label": "positive", "prob": 0.9}}
    for name in FACET_DIMENSION_IDS:
        votes[name] = {"label": "not-discussed", "prob": 0.7}
    return votes


# --- v1.2 評審團（C8，實作裁定 12）------------------------------------------


def _jury_votes(labels: dict[str, str] | None = None, *, members: list[str] | None = None) -> dict:
    """組出合法 juryVotes：成員短名 → 標籤（預設全 positive/not-discussed）。"""
    names = members or ["deepseek-v4.1-flash", "glm-5.3-flash", "gpt-6-luna", "qwen3.7-flash"]
    base = labels or {"overall": "positive"}
    votes = {}
    for facet in VOTE_IDS:
        value = base.get(facet, "not-discussed" if facet != "overall" else "positive")
        votes[facet] = {name: value for name in names}
    return votes


def _v12_record(*, votes: dict | None = None, jury: dict | None = None, judge: str | None = "llm-jury@a1b2c3d4") -> dict:
    record = copy.deepcopy(_seed_evidence_records()[0])
    record["votes"] = _valid_votes() if votes is None else votes
    record["juryVotes"] = _jury_votes() if jury is None else jury
    record["judge"] = judge
    return record


def _write_record(tmp_path: Path, record: dict, name: str = "record.jsonl") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def test_old_and_new_evidence_versions_are_recognised() -> None:
    """1.2 的分流靠 juryVotes／llm-jury judge；1.1 舊檔不受影響。"""
    assert EvidenceRecord.model_validate(_scored_evidence_record()) is not None
    assert EvidenceRecordV12.model_validate(_v12_record()) is not None


def test_real_laya_evidence_file_still_passes() -> None:
    """驗收：舊 1.1 evidence（data/evidence/2026-09-29.jsonl）仍要通過。"""
    assert validate_path(REAL_EVIDENCE) == []
    assert main(["validate", str(REAL_EVIDENCE)]) == 0


def test_v12_evidence_passes(tmp_path: Path) -> None:
    path = _write_record(tmp_path, _v12_record())
    assert validate_path(path) == []
    assert main(["validate", str(path)]) == 0


def test_v12_tie_null_label_and_prob_passes(tmp_path: Path) -> None:
    votes = _valid_votes()
    votes["speed"] = {"label": None, "prob": None}
    path = _write_record(tmp_path, _v12_record(votes=votes))
    assert validate_path(path) == []


def test_v12_half_null_vote_is_rejected(tmp_path: Path) -> None:
    votes = _valid_votes()
    votes["speed"] = {"label": None, "prob": 0.5}
    errors = validate_path(_write_record(tmp_path, _v12_record(votes=votes)))
    assert any("speed" in message for message in errors)


def test_v12_requires_jury_votes_when_scored(tmp_path: Path) -> None:
    record = _v12_record(jury=None)
    del record["juryVotes"]
    errors = validate_path(_write_record(tmp_path, record))
    assert any("juryVotes" in message for message in errors)


def test_v12_requires_llm_jury_judge_format(tmp_path: Path) -> None:
    errors = validate_path(_write_record(tmp_path, _v12_record(judge="laya@55cf4c4")))
    # judge 以 llm-jury@ 判定版本，因此要明白報格式不符。
    assert any("judge" in message for message in errors)


def test_v12_jury_votes_member_keys_must_be_consistent(tmp_path: Path) -> None:
    jury = _jury_votes()
    jury["speed"] = {"deepseek-v4.1-flash": "positive"}  # 成員鍵集合不同
    errors = validate_path(_write_record(tmp_path, _v12_record(jury=jury)))
    assert any("juryVotes" in message for message in errors)


def test_v12_jury_votes_rejects_invalid_label(tmp_path: Path) -> None:
    jury = _jury_votes()
    jury["quality"]["gpt-6-luna"] = "neutral"  # neutral 不屬於面向
    errors = validate_path(_write_record(tmp_path, _v12_record(jury=jury)))
    assert any("quality" in message for message in errors)


def test_v12_jury_evidence_extra_field_is_rejected(tmp_path: Path) -> None:
    record = _v12_record()
    record["oops"] = True
    errors = validate_path(_write_record(tmp_path, record))
    assert any("oops" in message for message in errors)


def test_v12_scores_document_passes() -> None:
    data = load_seed_scores()
    data["meta"]["schemaVersion"] = JURY_SCHEMA_VERSION
    data["meta"]["judge"] = {
        "kind": "llm-jury",
        "members": [
            "deepseek/deepseek-v4.1-flash",
            "z-ai/glm-5.3-flash",
            "openai/gpt-6-luna",
            "qwen/qwen3.7-flash",
        ],
        "calibrated": False,
    }
    document = ScoresDocument.model_validate(data)
    assert document.meta.schemaVersion == 1.2
    assert document.meta.judge.kind == "llm-jury"


def test_v12_scores_requires_jury_judge_shape(tmp_path: Path) -> None:
    data = load_seed_scores()
    data["meta"]["schemaVersion"] = JURY_SCHEMA_VERSION  # 仍是 laya judge
    errors = validate_path(write_json(tmp_path / "scores.json", data))
    assert any("judge" in message for message in errors)


def test_v11_scores_with_jury_judge_is_rejected(tmp_path: Path) -> None:
    data = load_seed_scores()
    data["meta"]["judge"] = {"kind": "llm-jury", "members": ["a/b"], "calibrated": False}
    errors = validate_path(write_json(tmp_path / "scores.json", data))
    assert any("judge" in message for message in errors)


# --- 合法 -------------------------------------------------------------------


def test_seed_scores_pass(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["validate", str(SEED_SCORES)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "符合 schema" in captured.out
    assert captured.err == ""


def test_seed_evidence_pass(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["validate", str(SEED_EVIDENCE)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "符合 schema" in captured.out


def test_validate_path_returns_no_errors_for_seed() -> None:
    assert validate_path(SEED_SCORES) == []
    assert validate_path(SEED_EVIDENCE) == []


# --- 故意改壞：scores.json --------------------------------------------------


def test_missing_field_is_reported_with_field_name(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        del data["models"][0]["confidence"]

    bad = write_broken_scores(tmp_path, mutate)
    errors = validate_path(bad)

    assert errors
    assert any("confidence" in message for message in errors)


def test_missing_top_level_section_is_reported(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        del data["meta"]

    bad = write_broken_scores(tmp_path, mutate)
    errors = validate_path(bad)

    assert any("meta" in message for message in errors)


def test_missing_meta_section_is_reported(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        del data["meta"]["sourcesCovered"]

    errors = validate_path(write_broken_scores(tmp_path, mutate))

    assert any("sourcesCovered" in message for message in errors)


def test_wrong_type_is_reported_with_field_name(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["models"][0]["score"] = "高分"

    bad = write_broken_scores(tmp_path, mutate)
    errors = validate_path(bad)

    assert any("models[0].score" in message for message in errors)


def test_out_of_range_score_is_reported(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["models"][1]["dimensions"]["quality"] = 120

    bad = write_broken_scores(tmp_path, mutate)
    errors = validate_path(bad)

    assert any("quality" in message for message in errors)


def test_dimension_null_is_allowed(tmp_path: Path) -> None:
    """「資料不足」＝null，是合法值（不得顯示成 50）。"""
    def mutate(data: dict) -> None:
        data["models"][0]["dimensions"]["tokenUsage"] = None

    assert validate_path(write_broken_scores(tmp_path, mutate)) == []


def test_dimension_samples_negative_is_reported(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["models"][0]["dimensionSamples"]["quality"] = -1

    errors = validate_path(write_broken_scores(tmp_path, mutate))

    assert any("dimensionSamples" in message for message in errors)


def test_weights_out_of_range_is_reported(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["meta"]["weights"]["quality"] = 1.5

    errors = validate_path(write_broken_scores(tmp_path, mutate))

    assert any("weights" in message for message in errors)


def test_unknown_field_is_reported(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["models"][0]["oops"] = True

    bad = write_broken_scores(tmp_path, mutate)
    errors = validate_path(bad)

    assert any("oops" in message for message in errors)


def test_price_moved_to_model_level_old_location_is_rejected(tmp_path: Path) -> None:
    """v1.1 起 priceUsdPerMTok 在 model 層級；塞進 dimensions 應被擋。"""
    def mutate(data: dict) -> None:
        data["models"][0]["dimensions"]["priceUsdPerMTok"] = {"in": 1.0, "out": 2.0}

    errors = validate_path(write_broken_scores(tmp_path, mutate))

    assert any("priceUsdPerMTok" in message for message in errors)


def test_bad_evidence_ref_is_reported(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["models"][0]["evidence"] = ["nope.txt#l1"]

    bad = write_broken_scores(tmp_path, mutate)
    errors = validate_path(bad)

    assert any("evidence" in message for message in errors)


def test_invalid_json_is_reported(tmp_path: Path) -> None:
    bad = tmp_path / "scores.json"
    bad.write_text("{ not json", encoding="utf-8")
    errors = validate_path(bad)

    assert any("JSON 解析失敗" in message for message in errors)


def test_missing_file_is_reported(tmp_path: Path) -> None:
    errors = validate_path(tmp_path / "does-not-exist.json")

    assert any("找不到檔案" in message for message in errors)


def test_unsupported_suffix_is_reported(tmp_path: Path) -> None:
    bogus = tmp_path / "scores.yaml"
    bogus.write_text("meta: {}", encoding="utf-8")

    assert validate_path(bogus)


# --- dimensions 鍵交叉檢查（實作裁定第 9 條）--------------------------------


def test_dimensions_extra_key_is_reported(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["models"][0]["dimensions"]["frontendFit"] = 60.0

    errors = validate_path(write_broken_scores(tmp_path, mutate))

    assert any("models[0].dimensions" in message for message in errors)
    assert any("frontendFit" in message for message in errors)


def test_dimensions_missing_key_is_reported(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        del data["models"][1]["dimensions"]["speed"]

    errors = validate_path(write_broken_scores(tmp_path, mutate))

    assert any("models[1].dimensions" in message for message in errors)
    assert any("speed" in message for message in errors)


# --- 故意改壞：evidence.jsonl ----------------------------------------------


def _seed_evidence_records() -> list[dict]:
    return [
        json.loads(line)
        for line in SEED_EVIDENCE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_broken_evidence(tmp_path: Path, mutate) -> Path:
    record = copy.deepcopy(_seed_evidence_records()[0])
    mutate(record)
    bad = tmp_path / "evidence.jsonl"
    bad.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    return bad


def _scored_evidence_record() -> dict:
    record = copy.deepcopy(_seed_evidence_records()[0])
    record["votes"] = _valid_votes()
    record["judge"] = "laya@55cf4c4"
    return record


def test_invalid_overall_label_is_reported(tmp_path: Path) -> None:
    """overall 只接受 positive／negative／neutral（neutral 之外的 not-discussed 不行）。"""
    def mutate(record: dict) -> None:
        record["votes"] = _valid_votes()
        record["votes"]["overall"]["label"] = "not-discussed"

    errors = validate_path(_write_broken_evidence(tmp_path, mutate))

    assert any("overall" in message and "label" in message for message in errors)
    assert any("第 1 行" in message for message in errors)


def test_facet_neutral_label_is_reported(tmp_path: Path) -> None:
    """面向維度不接受 neutral（neutral 只屬於 overall，裁定第 8 條）。"""
    def mutate(record: dict) -> None:
        record["votes"] = _valid_votes()
        record["votes"]["quality"]["label"] = "neutral"

    errors = validate_path(_write_broken_evidence(tmp_path, mutate))

    assert any("quality" in message for message in errors)


def test_votes_missing_key_is_reported_with_key_name(tmp_path: Path) -> None:
    def mutate(record: dict) -> None:
        record["votes"] = _valid_votes()
        del record["votes"]["speed"]

    errors = validate_path(_write_broken_evidence(tmp_path, mutate))

    assert any("speed" in message for message in errors)


def test_votes_extra_key_is_reported_with_key_name(tmp_path: Path) -> None:
    def mutate(record: dict) -> None:
        record["votes"] = _valid_votes()
        record["votes"]["vibes"] = {"label": "positive", "prob": 0.5}

    errors = validate_path(_write_broken_evidence(tmp_path, mutate))

    assert any("vibes" in message for message in errors)


def test_prob_out_of_range_is_reported(tmp_path: Path) -> None:
    def mutate(record: dict) -> None:
        record["votes"] = _valid_votes()
        record["votes"]["quality"]["prob"] = 1.5

    errors = validate_path(_write_broken_evidence(tmp_path, mutate))

    assert any("prob" in message for message in errors)


def test_bad_line_number_is_reported(tmp_path: Path) -> None:
    records = _seed_evidence_records()
    records[1]["votes"] = _valid_votes()
    records[1]["votes"]["overall"]["prob"] = -0.1
    bad = tmp_path / "evidence.jsonl"
    bad.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )

    errors = validate_path(bad)

    assert any("第 2 行" in message for message in errors)
    assert any("prob" in message for message in errors)


# --- 未評分 evidence（votes/judge 為 null）----------------------------------


def test_unscored_evidence_with_null_votes_passes(tmp_path: Path) -> None:
    """plan.md 實作裁定第 7 條：結構合法但未評分＝合法。"""
    record = copy.deepcopy(_seed_evidence_records()[0])
    record["votes"] = None
    record["judge"] = None
    path = tmp_path / "unscored.jsonl"
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    assert validate_path(path) == []
    assert main(["validate", str(path)]) == 0


def test_evidence_with_null_author_passes(tmp_path: Path) -> None:
    """plan.md 實作裁定第 6 條：author 允許 null（last30days 常缺作者）。"""
    record = copy.deepcopy(_seed_evidence_records()[0])
    record["author"] = None
    path = tmp_path / "no-author.jsonl"
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    assert validate_path(path) == []
    assert main(["validate", str(path)]) == 0
    assert EvidenceRecord.model_validate(record).author is None


def test_scored_evidence_passes(tmp_path: Path) -> None:
    record = _scored_evidence_record()
    path = tmp_path / "scored.jsonl"
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    assert validate_path(path) == []
    parsed = EvidenceRecord.model_validate(record)
    assert parsed.votes is not None
    assert tuple(parsed.votes.model_dump()) == VOTE_IDS
    assert parsed.judge == "laya@55cf4c4"


# --- schema 模型與 scores.json 交叉檢查 -------------------------------------


def test_scores_document_validates_against_schema() -> None:
    document = ScoresDocument.model_validate(load_seed_scores())

    assert document.meta.schemaVersion == 1.1
    assert document.meta.kind == "community-sentiment"
    assert len(document.models) >= 1
    # 分數是公式算出來的社群資料，未經 C5 校準，必須如實標示。
    assert document.meta.judge.calibrated is False
    # 窗口偏誤說明必須在（C4 產出的 notes 含「窗口」字樣）。
    assert "窗口" in document.meta.notes
    # 站方表格欄位由 meta.dimensions 驅動。
    assert [spec.id for spec in document.meta.dimensions] == list(FACET_DIMENSION_IDS)
    # sourcesCovered 是實際出現的來源、排序過且非空。
    assert document.meta.sourcesCovered
    assert document.meta.sourcesCovered == sorted(document.meta.sourcesCovered)
    assert set(document.meta.weights) == set(FACET_DIMENSION_IDS)
    # 每個模型的 dimensions 鍵都恰好等於 meta.dimensions。
    declared = {spec.id for spec in document.meta.dimensions}
    for model in document.models:
        assert set(model.dimensions) == declared


def test_seed_evidence_refs_point_to_real_lines() -> None:
    """每個 model 的 evidence 參照都要真的指向 evidence 檔的對應行與模型。"""
    scores = load_seed_scores()
    # C4 產出的 evidence 參照格式為 `evidence/<檔名>#l<行號>`，故基準目錄是 data/。
    evidence_dir = SEED_SCORES.parent

    for model in scores["models"]:
        assert model["evidence"], f"{model['id']} 沒有 evidence 參照"
        for ref in model["evidence"]:
            file_part, _, line_part = ref.partition("#l")
            line_number = int(line_part)
            evidence_path = evidence_dir / file_part
            assert evidence_path.exists(), f"找不到 evidence 檔：{ref}"

            lines = [
                line
                for line in evidence_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            assert 1 <= line_number <= len(lines), f"{ref} 行號超出範圍"
            record = EvidenceRecord.model_validate(json.loads(lines[line_number - 1]))
            assert record.modelId == model["id"], f"{ref} 不屬於 {model['id']}"


def test_seed_model_ids_are_unique() -> None:
    models = load_seed_scores()["models"]
    ids = [model["id"] for model in models]

    assert len(ids) == len(set(ids))


def test_other_pipeline_commands_not_replying_validate_exit_codes() -> None:
    """C4 完成後 build 不再回「未實作」的 3；實際行為由 tests/test_build.py 驗證。"""
    assert main(["build"]) != 3
