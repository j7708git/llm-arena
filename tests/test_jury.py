"""`arena score` 的 LLM 評審團測試（任務 C8）。

全程離線：HTTP 以 ``httpx.MockTransport`` 注入，或直接注入假 client；重試的等待以
``sleep`` 注入的 no-op 取代。測試不得打真網路。
"""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import httpx
import pytest

from arena import jury
from arena.cli import build_parser, main
from arena.jury import (
    JuryPredictor,
    OpenRouterChatClient,
    aggregate_member_labels,
    api_model_id,
    build_messages,
    jury_judge,
    member_short_name,
    members_hash,
    parse_member_labels,
)
from arena.score import EXIT_ERROR, EXIT_OK, Prediction, Vote, run
from arena.schema import FACET_DIMENSION_IDS, OVERALL_VOTE_ID, VOTE_IDS
from arena.validate import validate_path

ROOT = Path(__file__).resolve().parents[1]
SEED_EVIDENCE = ROOT / "data" / "samples" / "evidence.sample.jsonl"

DEEPSEEK, GLM, GPT, QWEN = (
    "deepseek/deepseek-v4.1-flash",
    "z-ai/glm-5.3-flash",
    "openai/gpt-6-luna",
    "qwen/qwen3.7-flash",
)
# 測試用四人名單（驗多數決機制用；正式預設已收斂為單一評審，見 jury.JURY_MEMBERS）。
TEST_MEMBERS = (DEEPSEEK, GLM, GPT, QWEN)
SHORT = {member: member_short_name(member) for member in TEST_MEMBERS}


# --- 工具 ---------------------------------------------------------------------


def _labels(**overrides: str) -> dict[str, str]:
    """六鍵標籤；預設 overall=neutral、面向=not-discussed。"""
    labels = {
        facet: ("neutral" if facet == OVERALL_VOTE_ID else "not-discussed")
        for facet in VOTE_IDS
    }
    labels.update(overrides)
    return labels


def _labels_json(**overrides: str) -> str:
    return json.dumps(_labels(**overrides), ensure_ascii=False)


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": content}}]}
    )


def _sync_transport(replies: dict[str, str], *, calls: list[dict] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path.endswith("/chat/completions")
        if calls is not None:
            calls.append(body)
        reply = replies.get(body["model"])
        if reply is None:
            return httpx.Response(404, json={"error": "unknown model"})
        return _chat_response(reply)

    return httpx.MockTransport(handler)


def _client(transport, *, key: str = "test-key", **kwargs) -> OpenRouterChatClient:
    kwargs.setdefault("backoff_seconds", 0.0)
    kwargs.setdefault("sleep", lambda _seconds: None)
    return OpenRouterChatClient(key, transport=transport, **kwargs)


def _record(*, text: str = "A post about a model.", model_id: str = "vendor/m") -> dict:
    return {
        "hash": "h1",
        "modelId": model_id,
        "source": "reddit",
        "url": "https://example.com/post",
        "author": None,
        "postedAt": "2026-09-24T00:00:00Z",
        "text": text,
        "votes": None,
        "judge": None,
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


# --- 成員識別 / judge ---------------------------------------------------------


def test_members_hash_is_order_independent_and_deterministic() -> None:
    assert members_hash(TEST_MEMBERS) == members_hash(reversed(TEST_MEMBERS))
    assert members_hash(TEST_MEMBERS) == members_hash(list(TEST_MEMBERS))
    assert len(members_hash()) == 64


def test_jury_judge_format() -> None:
    import re

    assert re.fullmatch(r"llm-jury@[0-9a-f]{8}", jury_judge())
    # hash 是 members 排序後串接的 sha256 前 8 碼。
    assert jury_judge() == f"llm-jury@{members_hash()[:8]}"


def test_member_short_names() -> None:
    assert member_short_name("deepseek/deepseek-v4.1-flash") == "deepseek-v4.1-flash"
    assert member_short_name("qwen/qwen3.7-flash") == "qwen3.7-flash"


def test_api_model_id_adds_batch_except_qwen() -> None:
    assert api_model_id(DEEPSEEK, use_batch=True) == f"{DEEPSEEK}:batch"
    assert api_model_id(GLM, use_batch=True) == f"{GLM}:batch"
    assert api_model_id(GPT, use_batch=True) == f"{GPT}:batch"
    # qwen 無 batch 版 → 任何模式都原價。
    assert api_model_id(QWEN, use_batch=True) == QWEN
    assert api_model_id(QWEN, use_batch=False) == QWEN
    assert api_model_id(DEEPSEEK, use_batch=False) == DEEPSEEK


# --- prompt -------------------------------------------------------------------


def test_prompt_contains_rubric_and_only_post_text() -> None:
    model_id = "vendor/secret-model-name"
    messages = build_messages("This model is great.")
    blob = json.dumps(messages, ensure_ascii=False)

    assert messages[0]["role"] == "system"
    for facet in VOTE_IDS:
        assert facet in blob
    # 六題齊全、標籤集正確。
    assert "not-discussed" in blob and "neutral" in blob
    assert model_id not in blob
    assert "This model is great." in blob


def test_prompt_is_deterministic() -> None:
    assert build_messages("same post") == build_messages("same post")


# --- 解析 ---------------------------------------------------------------------


def test_parse_member_labels_tolerates_code_fence() -> None:
    content = "```json\n" + _labels_json(overall="positive") + "\n```"
    assert parse_member_labels(content)[OVERALL_VOTE_ID] == "positive"


def test_parse_member_labels_rejects_invalid_labels() -> None:
    labels = parse_member_labels(
        json.dumps({"overall": "not-discussed", "quality": "maybe"})
    )
    assert labels[OVERALL_VOTE_ID] is None  # not-discussed 不屬於 overall
    assert labels["quality"] is None  # 非允許標籤
    assert labels["speed"] is None  # 缺鍵


def test_parse_member_labels_rejects_non_json() -> None:
    with pytest.raises(ValueError):
        parse_member_labels("sorry, I cannot help with that")


# --- 聚合（實作裁定 12）-------------------------------------------------------


def _per_member(**by_member: str) -> dict[str, dict[str, str] | None]:
    """以成員短名或全名組出 per_member；值為 overall 標籤，其餘 not-discussed。"""
    result: dict[str, dict[str, str] | None] = {}
    for member in TEST_MEMBERS:
        short = member_short_name(member)
        if short in by_member:
            result[member] = _labels(overall=by_member[short])
        else:
            result[member] = _labels()
    return result


def test_majority_three_of_four_prob_075() -> None:
    outcome = aggregate_member_labels(
        members=TEST_MEMBERS,
        per_member=_per_member(**{SHORT[DEEPSEEK]: "positive", SHORT[GLM]: "positive", SHORT[GPT]: "positive"})
    )
    vote = outcome.votes[OVERALL_VOTE_ID]
    assert vote.label == "positive"
    assert vote.prob == pytest.approx(0.75)


def test_unanimous_prob_1() -> None:
    outcome = aggregate_member_labels(
        members=TEST_MEMBERS,
        per_member=_per_member(**{SHORT[m]: "negative" for m in TEST_MEMBERS})
    )
    assert outcome.votes[OVERALL_VOTE_ID] == Vote("negative", 1.0)


def test_two_two_tie_is_null() -> None:
    outcome = aggregate_member_labels(
        members=TEST_MEMBERS,
        per_member=_per_member(
            **{SHORT[DEEPSEEK]: "positive", SHORT[GLM]: "positive",
               SHORT[GPT]: "negative", SHORT[QWEN]: "negative"}
        )
    )
    assert outcome.votes[OVERALL_VOTE_ID] == Vote(None, None)
    # 逐票仍完整保留。
    assert outcome.jury_votes[OVERALL_VOTE_ID][SHORT[GPT]] == "negative"


def test_two_one_one_picks_majority() -> None:
    outcome = aggregate_member_labels(
        members=TEST_MEMBERS,
        per_member=_per_member(
            **{SHORT[DEEPSEEK]: "positive", SHORT[GLM]: "positive",
               SHORT[GPT]: "negative", SHORT[QWEN]: "neutral"}
        )
    )
    assert outcome.votes[OVERALL_VOTE_ID] == Vote("positive", 0.5)


def test_none_vote_on_failed_member_makes_post_void() -> None:
    per_member = _per_member(**{SHORT[m]: "positive" for m in TEST_MEMBERS})
    per_member[GLM] = None

    outcome = aggregate_member_labels(per_member, members=TEST_MEMBERS)

    assert outcome.votes is None
    # 失敗成員的票記 null，其餘保留。
    assert outcome.jury_votes[OVERALL_VOTE_ID][SHORT[GLM]] is None
    assert outcome.jury_votes[OVERALL_VOTE_ID][SHORT[DEEPSEEK]] == "positive"


def test_facet_with_no_valid_votes_is_null_while_post_scored() -> None:
    """成員都回覆成功、但某面向四票全缺 → 該面向 null，其餘照常（整則不算作廢）。"""
    per_member = {
        member: {facet: None for facet in VOTE_IDS} | {OVERALL_VOTE_ID: "positive"}
        for member in TEST_MEMBERS
    }

    outcome = aggregate_member_labels(per_member, members=TEST_MEMBERS)

    assert outcome.votes is not None
    assert outcome.votes[OVERALL_VOTE_ID] == Vote("positive", 1.0)
    assert outcome.votes["speed"] == Vote(None, None)


# --- 端到端：同步 --------------------------------------------------------------


def _sync_replies(**by_short: str) -> dict[str, str]:
    replies = {}
    for member in TEST_MEMBERS:
        short = member_short_name(member)
        replies[member] = _labels_json(
            overall=by_short.get(short, "neutral"),
            quality=by_short.get(short, "not-discussed"),
        )
    return replies


def test_sync_run_backfills_votes_juryvotes_and_judge(tmp_path: Path) -> None:
    path = _write(tmp_path / "e.jsonl", [_record(text="score me")])
    calls: list[dict] = []
    replies = {
        DEEPSEEK: _labels_json(overall="positive", quality="positive"),
        GLM: _labels_json(overall="positive", quality="positive"),
        GPT: _labels_json(overall="positive", quality="positive"),
        QWEN: _labels_json(overall="negative", quality="negative"),
    }
    predictor = JuryPredictor(
        _client(_sync_transport(replies, calls=calls)), members=TEST_MEMBERS,
        use_batch=False,
    )

    assert run(Namespace(files=[str(path)], force=False), predictor=predictor) == EXIT_OK

    record = _read(path)[0]
    assert record["votes"][OVERALL_VOTE_ID] == {"label": "positive", "prob": 0.75}
    assert record["votes"]["quality"] == {"label": "positive", "prob": 0.75}
    assert record["votes"]["speed"]["label"] == "not-discussed"
    assert record["judge"] == jury_judge(TEST_MEMBERS)
    assert set(record["juryVotes"]) == set(VOTE_IDS)
    assert record["juryVotes"][OVERALL_VOTE_ID][SHORT[QWEN]] == "negative"
    # 獨立呼叫：四位各一次、同一 prompt、溫度 0、只帶貼文。
    assert len(calls) == 4
    assert all(body["temperature"] == 0 for body in calls)
    assert all(body["model"] in TEST_MEMBERS for body in calls)  # 同步版無 :batch
    assert all("score me" in body["messages"][1]["content"] for body in calls)
    assert all("vendor/m" not in json.dumps(body) for body in calls)
    # 產出必須是合法 v1.2 evidence。
    assert validate_path(path) == []


def test_sync_run_is_idempotent_and_does_not_call_again(tmp_path: Path) -> None:
    path = _write(tmp_path / "e.jsonl", [_record(text="once")])
    predictor = JuryPredictor(
        _client(_sync_transport(_sync_replies())), use_batch=False,
        members=TEST_MEMBERS,
    )
    assert run(Namespace(files=[str(path)]), predictor=predictor) == EXIT_OK
    first = path.read_bytes()

    class _Boom:
        def classify(self, states):  # pragma: no cover - 不該被呼叫
            raise AssertionError("第二次執行不應再呼叫評審")

    assert run(Namespace(files=[str(path)]), predictor=_Boom()) == EXIT_OK
    assert path.read_bytes() == first


def test_reproducible_for_fixed_inputs(tmp_path: Path) -> None:
    """溫度 0＋固定 prompt：同輸入重跑逐位元一致。"""
    records = [_record(text=f"text {i}") for i in range(3)]
    outputs = []
    for run_index in range(2):
        directory = tmp_path / f"run{run_index}"
        directory.mkdir()
        path = _write(directory / "e.jsonl", records)
        predictor = JuryPredictor(
            _client(_sync_transport(_sync_replies())), use_batch=False,
            members=TEST_MEMBERS,
        )
        assert run(Namespace(files=[str(path)]), predictor=predictor) == EXIT_OK
        outputs.append([json.dumps(record, ensure_ascii=False) for record in _read(path)])

    assert outputs[0] == outputs[1]


def test_force_with_laya_style_predictor_removes_jury_votes(tmp_path: Path) -> None:
    """重評（force）換回無 jury 的預測器時，舊 juryVotes 要清掉（schema extra=forbid）。"""
    path = _write(tmp_path / "e.jsonl", [_record(text="rescore")])
    jury_predictor = JuryPredictor(
        _client(_sync_transport(_sync_replies())), use_batch=False,
        members=TEST_MEMBERS,
    )
    assert run(Namespace(files=[str(path)]), predictor=jury_predictor) == EXIT_OK
    assert "juryVotes" in _read(path)[0]

    class _LayaStyle:
        judge = "laya@55cf4c4"

        def classify(self, states):
            votes = {
                facet: Vote("neutral" if facet == OVERALL_VOTE_ID else "not-discussed", 0.5)
                for facet in VOTE_IDS
            }
            return [Prediction(votes=votes) for _ in states]

    assert run(Namespace(files=[str(path)], force=True), predictor=_LayaStyle()) == EXIT_OK

    record = _read(path)[0]
    assert "juryVotes" not in record
    assert record["judge"] == "laya@55cf4c4"
    assert validate_path(path) == []


def test_two_two_tie_written_as_null_and_still_valid(tmp_path: Path) -> None:
    path = _write(tmp_path / "e.jsonl", [_record(text="tie")])
    replies = {
        DEEPSEEK: _labels_json(overall="positive"),
        GLM: _labels_json(overall="positive"),
        GPT: _labels_json(overall="negative"),
        QWEN: _labels_json(overall="negative"),
    }
    predictor = JuryPredictor(
        _client(_sync_transport(replies)), use_batch=False,
        members=TEST_MEMBERS,
        )

    assert run(Namespace(files=[str(path)]), predictor=predictor) == EXIT_OK

    record = _read(path)[0]
    assert record["votes"][OVERALL_VOTE_ID] == {"label": None, "prob": None}
    assert record["juryVotes"][OVERALL_VOTE_ID][SHORT[DEEPSEEK]] == "positive"
    assert validate_path(path) == []


def test_member_failure_voids_post_and_reports_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "e.jsonl", [_record(text="fail")])

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] == GLM:
            return httpx.Response(500, json={"error": "boom"})
        return _chat_response(_labels_json(overall="positive"))

    predictor = JuryPredictor(
        _client(httpx.MockTransport(handler)), use_batch=False, members=TEST_MEMBERS,
    )

    assert run(Namespace(files=[str(path)]), predictor=predictor) == EXIT_OK

    captured = capsys.readouterr()
    assert "評審呼叫失敗" in captured.err
    record = _read(path)[0]
    # 整則失敗 → 回到「未評分」狀態（votes/judge 皆 null、不寫 juryVotes）：
    # 帶 judge 的 votes=null 記錄不是合法 v1.2 形狀；重跑（或 --force）會自動重試。
    assert record["votes"] is None
    assert record["judge"] is None
    assert "juryVotes" not in record
    assert validate_path(path) == []


# --- 端到端：batch -------------------------------------------------------------


def _batch_transport(replies: dict[str, str], *, record: list[dict] | None = None):
    """每個成員一個 batch；POST 建立、GET 直接 completed。"""
    batches: dict[str, dict] = {}
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            # 無 batch 版成員（QWEN）退回同步呼叫。
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": replies[body["model"]]}}]
                },
            )
        if request.method == "POST":
            body = json.loads(request.content)
            state["n"] += 1
            batch_id = f"b{state['n']}"
            batches[batch_id] = body
            if record is not None:
                record.append(body)
            return httpx.Response(200, json={"id": batch_id, "status": "validating"})
        batch_id = request.url.path.rsplit("/", 1)[-1]
        body = batches[batch_id]
        content = replies[body["model"]]
        results = [
            {
                "custom_id": item["custom_id"],
                "response": {
                    "status_code": 200,
                    "body": {"choices": [{"message": {"content": content}}]},
                },
                "error": None,
            }
            for item in body["requests"]
        ]
        return httpx.Response(
            200, json={"id": batch_id, "status": "completed", "results": results}
        )

    return httpx.MockTransport(handler)


def test_batch_run_uses_batch_models_and_backfills(tmp_path: Path) -> None:
    path = _write(tmp_path / "e.jsonl", [_record(text="batch me")])
    posted: list[dict] = []
    replies = {
        f"{DEEPSEEK}:batch": _labels_json(overall="positive"),
        f"{GLM}:batch": _labels_json(overall="positive"),
        f"{GPT}:batch": _labels_json(overall="positive"),
        QWEN: _labels_json(overall="positive"),  # 無 batch 版用原價
    }
    predictor = JuryPredictor(
        _client(_batch_transport(replies, record=posted)), members=TEST_MEMBERS,
        use_batch=True,
    )

    assert run(Namespace(files=[str(path)]), predictor=predictor) == EXIT_OK

    record = _read(path)[0]
    assert record["votes"][OVERALL_VOTE_ID] == {"label": "positive", "prob": 1.0}
    # 有 batch 版的三個成員各一個 batch；QWEN 走同步不送 batch。
    assert len(posted) == 3
    models = {body["model"] for body in posted}
    assert models == {f"{DEEPSEEK}:batch", f"{GLM}:batch", f"{GPT}:batch"}
    for body in posted:
        assert body["endpoint"] == "/v1/chat/completions"
        assert body["requests"][0]["body"]["temperature"] == 0
    assert validate_path(path) == []


def test_batch_result_error_voids_that_member(tmp_path: Path) -> None:
    path = _write(tmp_path / "e.jsonl", [_record(text="batch fail")])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "b1", "status": "validating"})
        return httpx.Response(
            200,
            json={
                "id": "b1",
                "status": "completed",
                "results": [
                    {"custom_id": "p0", "response": None, "error": {"code": "expired"}}
                ],
            },
        )

    predictor = JuryPredictor(
        _client(httpx.MockTransport(handler)), members=(DEEPSEEK,), use_batch=True
    )
    assert run(Namespace(files=[str(path)]), predictor=predictor) == EXIT_OK

    record = _read(path)[0]
    # 整則失敗 → 未評分狀態（votes/judge null、不寫 juryVotes）。
    assert record["votes"] is None
    assert record["judge"] is None
    assert "juryVotes" not in record


def test_batch_poll_404_during_propagation_is_retried(tmp_path: Path) -> None:
    """剛建立的 batch GET 會先 404（同步延遲）：寬限期內應繼續輪詢而非失敗。"""
    path = _write(tmp_path / "e.jsonl", [_record(text="batch 404")])
    polls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "b1", "status": "validating"})
        polls["n"] += 1
        if polls["n"] <= 2:
            return httpx.Response(404, json={"error": "not found yet"})
        return httpx.Response(
            200,
            json={
                "id": "b1",
                "status": "completed",
                "results": [
                    {
                        "custom_id": "p0",
                        "response": {
                            "status_code": 200,
                            "body": {
                                "choices": [
                                    {
                                        "message": {
                                            "content": _labels_json(
                                                overall="positive"
                                            )
                                        }
                                    }
                                ]
                            },
                        },
                        "error": None,
                    }
                ],
            },
        )

    predictor = JuryPredictor(
        _client(httpx.MockTransport(handler)), members=(DEEPSEEK,), use_batch=True
    )
    assert run(Namespace(files=[str(path)]), predictor=predictor) == EXIT_OK

    record = _read(path)[0]
    assert record["votes"][OVERALL_VOTE_ID]["label"] == "positive"


def test_batch_poll_timeout_is_a_failure() -> None:
    calls = {"n": 0}
    ticks = iter([0.0, 100.0, 200.0, 300.0, 400.0])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "b1", "status": "validating"})
        calls["n"] += 1
        return httpx.Response(200, json={"id": "b1", "status": "validating"})

    client = OpenRouterChatClient(
        "k",
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
        clock=lambda: next(ticks),
        backoff_seconds=0.0,
    )
    predictor = JuryPredictor(
        client, members=(DEEPSEEK,), use_batch=True, batch_timeout=10.0
    )
    predictions = predictor.classify([{"post": "x"}])

    assert predictions[0].votes is None
    assert calls["n"] >= 1
    assert predictor.stats["member_failures"] == 1


# --- 重試 ---------------------------------------------------------------------


def test_retry_succeeds_after_429() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            return httpx.Response(429, json={"error": "slow down"})
        return _chat_response(_labels_json(overall="positive"))

    predictor = JuryPredictor(
        _client(httpx.MockTransport(handler)), members=(DEEPSEEK,), use_batch=False
    )
    outcome = predictor.classify([{"post": "retry"}])[0]

    assert attempts["n"] == 3
    assert outcome.votes[OVERALL_VOTE_ID] == Vote("positive", 1.0)


def test_retry_gives_up_after_max_retries() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(429, json={"error": "always"})

    predictor = JuryPredictor(
        _client(httpx.MockTransport(handler), max_retries=3),
        members=(DEEPSEEK,),
        use_batch=False,
    )
    outcome = predictor.classify([{"post": "give up"}])[0]

    assert attempts["n"] == 4  # 首次 + 3 次重試
    assert outcome.votes is None
    assert "評審呼叫失敗" in predictor.failure_report()


def test_non_retryable_http_error_fails_immediately() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(401, json={"error": "bad key"})

    predictor = JuryPredictor(
        _client(httpx.MockTransport(handler)), members=(DEEPSEEK,), use_batch=False
    )
    assert predictor.classify([{"post": "x"}])[0].votes is None
    assert attempts["n"] == 1


# --- 缺 key -------------------------------------------------------------------


def test_missing_api_key_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    path = _write(tmp_path / "e.jsonl", [_record(text="needs key")])

    assert run(Namespace(files=[str(path)])) == EXIT_ERROR

    captured = capsys.readouterr()
    assert "OPENROUTER_API_KEY" in captured.err
    # 沒有 key 不得寫檔、不得靜默降級。
    assert _read(path)[0]["votes"] is None


def test_build_jury_predictor_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    predictor = jury.build_jury_predictor(use_batch=False)
    assert predictor.use_batch is False
    assert predictor.judge == jury_judge()


# --- 金鑰來源（環境變數 → 專案 .env → 中央金鑰檔）------------------------------


def _isolate_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """把兩個 dotenv 來源都指到不存在的路徑（conftest 已做，這裡供個別測試覆寫）。"""
    monkeypatch.setenv(jury.DOTENV_ENV, str(tmp_path / "nonexistent-dotenv"))
    monkeypatch.setenv(jury.ENV_FILE_ENV, str(tmp_path / "nonexistent-central"))


def test_parse_env_file_handles_owner_format() -> None:
    text = "\n".join(
        [
            "# 註解",
            "(AERO15_Tools)",  # 分組標題：不含 = 應忽略
            "",
            "export OPENROUTER_API_KEY='sk-or-quoted'",
            'OPENROUTER_KEY="sk-or-double"',
            "OPENROUTER_KEY=sk-or-last-wins",
            "EMPTY_VALUE=",
        ]
    )
    values = jury.parse_env_file(text)
    assert values["OPENROUTER_API_KEY"] == "sk-or-quoted"
    assert values["OPENROUTER_KEY"] == "sk-or-last-wins"  # 後者覆蓋前者
    assert values["EMPTY_VALUE"] == ""
    assert "(AERO15_Tools)" not in values


def test_resolve_api_key_env_wins_over_all_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENROUTER_KEY=sk-or-from-dotenv\n", encoding="utf-8")
    central = tmp_path / "central.env"
    central.write_text("OPENROUTER_KEY=sk-or-from-central\n", encoding="utf-8")
    monkeypatch.setenv(jury.DOTENV_ENV, str(dotenv))
    monkeypatch.setenv(jury.ENV_FILE_ENV, str(central))
    monkeypatch.setenv(jury.API_KEY_ENV, "sk-or-from-env")
    assert jury.resolve_api_key() == "sk-or-from-env"


def test_resolve_api_key_project_dotenv_wins_over_central(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENROUTER_KEY=sk-or-from-dotenv\n", encoding="utf-8")
    central = tmp_path / "central.env"
    central.write_text("OPENROUTER_KEY=sk-or-from-central\n", encoding="utf-8")
    monkeypatch.setenv(jury.DOTENV_ENV, str(dotenv))
    monkeypatch.setenv(jury.ENV_FILE_ENV, str(central))
    assert jury.resolve_api_key() == "sk-or-from-dotenv"


def test_resolve_api_key_dotenv_points_to_central_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """專案 .env 內以 ARENA_ENV_FILE 指向中央金鑰檔（owner 的用法）。"""
    central = tmp_path / ".keys.env"
    central.write_text("(AERO15_Tools)\nOPENROUTER_KEY=sk-or-central\n", encoding="utf-8")
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{jury.ENV_FILE_ENV}={central}\n", encoding="utf-8")
    monkeypatch.delenv(jury.ENV_FILE_ENV, raising=False)
    monkeypatch.setenv(jury.DOTENV_ENV, str(dotenv))
    assert jury.resolve_api_key() == "sk-or-central"


def test_resolve_api_key_reports_all_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from arena.score import ScoreError

    dotenv = tmp_path / "no-dotenv"
    central = tmp_path / "no-central"
    monkeypatch.setenv(jury.DOTENV_ENV, str(dotenv))
    monkeypatch.setenv(jury.ENV_FILE_ENV, str(central))
    with pytest.raises(ScoreError) as excinfo:
        jury.resolve_api_key()
    message = str(excinfo.value)
    assert jury.API_KEY_ENV in message
    assert str(dotenv) in message
    assert str(central) in message


def test_resolve_api_key_rejects_blank_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from arena.score import ScoreError

    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENROUTER_KEY=   \n", encoding="utf-8")
    monkeypatch.setenv(jury.DOTENV_ENV, str(dotenv))
    monkeypatch.setenv(jury.ENV_FILE_ENV, str(tmp_path / "no-central"))
    with pytest.raises(ScoreError):
        jury.resolve_api_key()


def test_dotenv_and_env_file_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(jury.DOTENV_ENV, raising=False)
    monkeypatch.delenv(jury.ENV_FILE_ENV, raising=False)
    assert jury.dotenv_path() == jury.DEFAULT_DOTENV == jury.PROJECT_ROOT / ".env"
    assert jury.env_file_path() == jury.DEFAULT_ENV_FILE
    monkeypatch.setenv(jury.DOTENV_ENV, str(tmp_path / "custom.env"))
    assert jury.dotenv_path() == tmp_path / "custom.env"
    # 專案 .env 內的 ARENA_ENV_FILE 會覆蓋預設中央檔路徑。
    assert jury.env_file_path({jury.ENV_FILE_ENV: str(tmp_path / "central.env")}) == (
        tmp_path / "central.env"
    )


def test_client_rejects_empty_key() -> None:
    from arena.score import ScoreError

    with pytest.raises(ScoreError):
        OpenRouterChatClient("   ")


# --- CLI ----------------------------------------------------------------------


def test_add_arguments_exposes_batch_opt_in() -> None:
    parser = build_parser()
    namespace = parser.parse_args(["score"])
    assert getattr(namespace, "batch", False) is False  # 預設同步
    namespace = parser.parse_args(["score", "--batch", "--force"])
    assert namespace.batch is True
    assert namespace.force is True


def test_no_batch_env_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARENA_SCORE_NO_BATCH", "1")
    from arena.score import _env_flag

    assert _env_flag("ARENA_SCORE_NO_BATCH") is True


# --- 真評審團整合測試（需 key，預設跳過）-------------------------------------


@pytest.mark.skipif(
    not __import__("os").environ.get("OPENROUTER_API_KEY"),
    reason="真跑評審團需要 OPENROUTER_API_KEY（本機通常沒有）",
)
def test_real_jury_scores_sample(tmp_path: Path) -> None:
    """對 sample.jsonl 的 10 則真跑四人團（batch），回填 votes／juryVotes。"""
    records = [
        json.loads(line)
        for line in SEED_EVIDENCE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for record in records:
        record["votes"] = None
        record["judge"] = None
    path = _write(tmp_path / "e.jsonl", records)

    assert run(Namespace(files=[str(path)])) == EXIT_OK  # 預設同步

    for record in _read(path):
        assert record["judge"] == jury_judge(TEST_MEMBERS)
        assert validate_path(path) == []
        if record["votes"] is not None:
            assert set(record["votes"]) == set(VOTE_IDS)
        assert set(record["juryVotes"]) == set(VOTE_IDS)
