"""`arena score` 的測試（任務 C3）。

核心邏輯用假 predictor 注入，不載入真模型；真模型整合測試以 ``ARENA_RUN_SLOW=1``
閘門跳過，預設 CI 保持綠燈。
"""

from __future__ import annotations

import json
import os
from argparse import Namespace
from pathlib import Path

import pytest

from arena.cli import main
from arena.score import (
    DEFAULT_EVIDENCE_GLOB,
    EXIT_ERROR,
    EXIT_OK,
    JUDGE,
    LayaPredictor,
    Prediction,
    ScoreError,
    build_state,
    resolve_paths,
    run,
    score_paths,
)
from arena.validate import validate_path

ROOT = Path(__file__).resolve().parents[1]
SEED_EVIDENCE = ROOT / "data" / "evidence" / "sample.jsonl"


# --- 測試替身 ---------------------------------------------------------------


class FakePredictor:
    """依 text 查表回傳預測，並記錄收到的 state 以便斷言。"""

    def __init__(self, table: dict[str, Prediction] | None = None) -> None:
        self.table = table or {}
        self.calls: list[list[dict[str, str]]] = []

    def classify(self, states: list[dict[str, str]]) -> list[Prediction]:
        self.calls.append(states)
        return [
            self.table.get(state["post"], Prediction("neutral", 0.5)) for state in states
        ]

    @property
    def seen_texts(self) -> list[str]:
        return [state["post"] for call in self.calls for state in call]


class FailingPredictor:
    def classify(self, states: list[dict[str, str]]) -> list[Prediction]:
        raise ScoreError("模擬預測器失敗")


# --- 資料工具 ---------------------------------------------------------------


def _record(
    hash_: str,
    *,
    model_id: str = "anthropic/claude-sonnet-4",
    text: str = "This model is fine.",
    label: str | None = None,
    prob: float | None = None,
    judge: str | None = None,
) -> dict:
    return {
        "hash": hash_,
        "modelId": model_id,
        "source": "reddit",
        "url": "https://www.reddit.com/r/x/comments/abc/seed/",
        "author": "u/someone",
        "postedAt": "2026-09-24T14:32:00Z",
        "text": text,
        "label": label,
        "prob": prob,
        "judge": judge,
    }


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _read(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _run(path: Path, predictor, *, force: bool = False) -> int:
    args = Namespace(files=[str(path)], force=force)
    return run(args, predictor=predictor)


# --- 回填正確性 -------------------------------------------------------------


def test_backfills_unscored_fields(tmp_path: Path) -> None:
    path = _write(tmp_path / "e.jsonl", [_record("h1", text="Great model, love it.")])
    fake = FakePredictor({"Great model, love it.": Prediction("positive", 0.91)})

    assert _run(path, fake) == EXIT_OK

    record = _read(path)[0]
    assert record["label"] == "positive"
    assert record["prob"] == pytest.approx(0.91)
    assert record["judge"] == JUDGE
    assert record["judge"] == "laya@55cf4c4"
    # 回填後必須是合法 evidence。
    assert validate_path(path) == []


def test_prob_uses_answer_confidence_not_confidence(tmp_path: Path) -> None:
    """假的 laya agent 回傳兩種信心，確認取的是 answer_confidence。"""
    path = _write(tmp_path / "e.jsonl", [_record("h1", text="text")])

    class StubAgent:
        def predict_batch(self, states, questions, batch_size=None):
            return [
                {
                    "answers": {
                        "attitude": {
                            "choice": "negative",
                            "confidence": 0.42,
                            "answer_confidence": 0.93,
                        }
                    }
                }
            ]

    real = LayaPredictor(StubAgent())
    assert _run(path, real) == EXIT_OK

    record = _read(path)[0]
    assert record["label"] == "negative"
    assert record["prob"] == pytest.approx(0.93)


def test_state_contains_only_post_text(tmp_path: Path) -> None:
    model_id = "vendor/secret-model-name"
    text = "Neutral observation about something."
    path = _write(
        tmp_path / "e.jsonl",
        [_record("h1", model_id=model_id, text=text)],
    )
    fake = FakePredictor()

    assert _run(path, fake) == EXIT_OK

    assert fake.calls == [[{"post": text}]]
    blob = json.dumps(fake.calls[0], ensure_ascii=False)
    assert model_id not in blob
    assert "secret-model-name" not in blob


def test_build_state_only_has_post_key() -> None:
    assert build_state(_record("h1", text="hello")) == {"post": "hello"}


# --- 冪等與 force -----------------------------------------------------------


def test_skips_already_labeled_lines(tmp_path: Path) -> None:
    labeled = _record(
        "h1", text="already scored", label="positive", prob=0.8, judge="laya@abc1234"
    )
    unscored = _record("h2", text="needs scoring")
    path = _write(tmp_path / "e.jsonl", [labeled, unscored])
    original_lines = path.read_text(encoding="utf-8").splitlines()
    fake = FakePredictor({"needs scoring": Prediction("negative", 0.7)})

    assert _run(path, fake) == EXIT_OK

    assert fake.seen_texts == ["needs scoring"]
    records = _read(path)
    # 已評分的行原封不動。
    assert records[0]["label"] == "positive"
    assert records[0]["prob"] == pytest.approx(0.8)
    assert records[0]["judge"] == "laya@abc1234"
    assert json.dumps(records[0], ensure_ascii=False) == original_lines[0]
    # 未評分的行被回填。
    assert records[1]["label"] == "negative"
    assert records[1]["judge"] == JUDGE


def test_second_run_is_idempotent_and_does_not_load_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path / "e.jsonl", [_record("h1", text="score me")])
    assert _run(path, FakePredictor()) == EXIT_OK
    after_first = path.read_bytes()

    def _boom(*args, **kwargs):
        raise AssertionError("第二次執行不應載入模型")

    monkeypatch.setattr(LayaPredictor, "load", classmethod(_boom))
    # 不再注入 predictor → 若真的想載入模型就會爆。
    assert run(Namespace(files=[str(path)])) == EXIT_OK

    assert path.read_bytes() == after_first


def test_force_re_evaluates_all_lines(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "e.jsonl",
        [_record("h1", text="t", label="positive", prob=0.9, judge="laya@abc1234")],
    )
    fake = FakePredictor({"t": Prediction("negative", 0.2)})

    assert _run(path, fake, force=True) == EXIT_OK

    record = _read(path)[0]
    assert record["label"] == "negative"
    assert record["prob"] == pytest.approx(0.2)
    assert record["judge"] == JUDGE


# --- 原子寫入 ---------------------------------------------------------------


def test_failure_leaves_original_file_intact(tmp_path: Path) -> None:
    path = _write(tmp_path / "e.jsonl", [_record("h1", text="score me")])
    original = path.read_bytes()

    assert _run(path, FailingPredictor()) == EXIT_ERROR

    assert path.read_bytes() == original
    # 不留下暫存檔。
    assert sorted(item.name for item in tmp_path.iterdir()) == ["e.jsonl"]


def test_atomic_write_replaces_without_leftover_temp(tmp_path: Path) -> None:
    path = _write(tmp_path / "e.jsonl", [_record("h1", text="x")])

    assert _run(path, FakePredictor()) == EXIT_OK

    assert sorted(item.name for item in tmp_path.iterdir()) == ["e.jsonl"]
    assert _read(path)[0]["judge"] == JUDGE


def test_multiple_lines_backfilled_in_one_run(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "e.jsonl",
        [_record("h1", text="a"), _record("h2", text="b"), _record("h3", text="c")],
    )
    fake = FakePredictor(
        {
            "a": Prediction("positive", 0.9),
            "b": Prediction("negative", 0.8),
            "c": Prediction("neutral", 0.6),
        }
    )

    assert _run(path, fake) == EXIT_OK

    assert len(fake.calls) == 1  # 未評分的行一次送評
    labels = [record["label"] for record in _read(path)]
    assert labels == ["positive", "negative", "neutral"]


# --- 可重現性 ---------------------------------------------------------------


def test_reproducible_for_fixed_inputs(tmp_path: Path) -> None:
    records = [_record(f"h{i}", text=f"text {i}") for i in range(5)]

    outputs = []
    for run_index in range(2):
        directory = tmp_path / f"run{run_index}"
        directory.mkdir()
        path = _write(directory / "e.jsonl", records)
        # 同一組輸入、同一個 predictor 實作 → 結果必須逐位元一致。
        table = {f"text {i}": Prediction("neutral", 0.5) for i in range(5)}
        score_paths([path], FakePredictor(table))
        outputs.append([record for record in _read(path)])

    assert outputs[0] == outputs[1]


# --- run() 的輸入處理 -------------------------------------------------------


def test_no_pending_does_not_load_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(
        tmp_path / "e.jsonl",
        [_record("h1", text="t", label="neutral", prob=0.7, judge=JUDGE)],
    )

    def _boom(*args, **kwargs):
        raise AssertionError("沒有待評分項時不應載入模型")

    monkeypatch.setattr(LayaPredictor, "load", classmethod(_boom))
    assert run(Namespace(files=[str(path)])) == EXIT_OK


def test_missing_file_returns_error(tmp_path: Path) -> None:
    assert run(Namespace(files=[str(tmp_path / "nope.jsonl")])) == EXIT_ERROR


def test_empty_directory_returns_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert run(Namespace()) == EXIT_ERROR


def test_resolve_paths_prefers_args(tmp_path: Path) -> None:
    target = tmp_path / "one.jsonl"
    assert resolve_paths(Namespace(files=[str(target)])) == [target]


def test_resolve_paths_uses_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    monkeypatch.setenv("ARENA_EVIDENCE_FILES", f"{first}{os.pathsep}{second}")
    assert resolve_paths(Namespace()) == [first, second]


def test_default_glob_constant() -> None:
    assert DEFAULT_EVIDENCE_GLOB == "data/evidence/*.jsonl"


def test_malformed_json_is_reported_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "e.jsonl"
    path.write_text("{ not json }\n", encoding="utf-8")
    original = path.read_bytes()

    assert _run(path, FakePredictor()) == EXIT_ERROR
    assert path.read_bytes() == original


# --- CLI --------------------------------------------------------------------


def test_score_help_is_available(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--help"])

    assert excinfo.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()


# --- 真模型整合測試（預設跳過）---------------------------------------------


@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_SLOW") != "1",
    reason="慢速整合測試：需下載 ~842MB 權重，設 ARENA_RUN_SLOW=1 才跑",
)
def test_real_laya_scores_sample_reproducibly(tmp_path: Path) -> None:
    """對 sample.jsonl 的 10 則（未評分副本）跑真 laya，並驗證同 process 可重現。"""
    records = [
        json.loads(line)
        for line in SEED_EVIDENCE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for record in records:
        record["label"] = None
        record["prob"] = None
        record["judge"] = None

    predictor = LayaPredictor.load()
    results = []
    for run_index in range(2):
        directory = tmp_path / f"real{run_index}"
        directory.mkdir()
        path = _write(directory / "e.jsonl", records)
        assert score_paths([path], predictor) == EXIT_OK
        scored = _read(path)
        assert all(record["judge"] == JUDGE for record in scored)
        assert all(record["label"] in {"positive", "negative", "neutral"} for record in scored)
        results.append([(record["label"], record["prob"]) for record in scored])

    assert results[0] == results[1]