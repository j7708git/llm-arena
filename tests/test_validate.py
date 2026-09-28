"""`arena validate` 的測試：合法種子通過、各種改壞的檔要被擋下並指出欄位。

壞檔一律寫到 pytest 的 tmp_path，不留在 repo 裡。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from arena.cli import EXIT_NOT_IMPLEMENTED, main
from arena.schema import EvidenceRecord, ScoresDocument
from arena.validate import validate_path

ROOT = Path(__file__).resolve().parents[1]
SEED_SCORES = ROOT / "data" / "scores.json"
SEED_EVIDENCE = ROOT / "data" / "evidence" / "sample.jsonl"


def load_seed_scores() -> dict:
    return json.loads(SEED_SCORES.read_text(encoding="utf-8"))


def write_json(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_broken_scores(tmp_path: Path, mutate) -> Path:
    data = copy.deepcopy(load_seed_scores())
    mutate(data)
    return write_json(tmp_path / "scores.json", data)


# --- 合法 -------------------------------------------------------------------


def test_seed_scores_pass(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["validate", str(SEED_SCORES)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "符合 schema v1" in captured.out
    assert captured.err == ""


def test_seed_evidence_pass(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["validate", str(SEED_EVIDENCE)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "符合 schema v1" in captured.out


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


def test_unknown_field_is_reported(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["models"][0]["oops"] = True

    bad = write_broken_scores(tmp_path, mutate)
    errors = validate_path(bad)

    assert any("oops" in message for message in errors)


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


def test_invalid_label_is_reported(tmp_path: Path) -> None:
    def mutate(record: dict) -> None:
        record["label"] = "mixed"

    errors = validate_path(_write_broken_evidence(tmp_path, mutate))

    assert any("label" in message for message in errors)
    assert any("第 1 行" in message for message in errors)


def test_prob_out_of_range_is_reported(tmp_path: Path) -> None:
    def mutate(record: dict) -> None:
        record["prob"] = 1.5

    errors = validate_path(_write_broken_evidence(tmp_path, mutate))

    assert any("prob" in message for message in errors)


def test_bad_line_number_is_reported(tmp_path: Path) -> None:
    records = _seed_evidence_records()
    records[1]["prob"] = -0.1
    bad = tmp_path / "evidence.jsonl"
    bad.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )

    errors = validate_path(bad)

    assert any("第 2 行" in message for message in errors)
    assert any("prob" in message for message in errors)


# --- schema 模型與種子資料交叉檢查 -----------------------------------------


def test_seed_models_validate_against_schema() -> None:
    document = ScoresDocument.model_validate(load_seed_scores())

    assert document.meta.schemaVersion == 1
    assert document.meta.kind == "community-sentiment"
    assert 3 <= len(document.models) <= 5
    # 種子資料必須自我標示是假資料
    assert "種子" in document.meta.notes


def test_seed_evidence_refs_point_to_real_lines() -> None:
    """每個 model 的 evidence 參照都要真的指向 evidence 檔的對應行與模型。"""
    scores = load_seed_scores()
    evidence_dir = SEED_SCORES.parent / "evidence"

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


def test_validate_keeps_unimplemented_exit_code() -> None:
    """確認沒有動到其他子命令的結束碼合約。"""
    assert main(["build"]) == EXIT_NOT_IMPLEMENTED
