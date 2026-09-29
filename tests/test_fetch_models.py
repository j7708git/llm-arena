"""`arena fetch-models`（C1）的測試。

**完全不碰真實網路**：純解析用 fixture、`fetch_models` 的 I/O 用
``httpx.MockTransport``、`run` 則把抓取函式 monkeypatch 掉。另有一個 autouse
fixture 把預設抓取換成一律失敗，確保任何忘記 mock 的測試會立刻炸掉而不是連外。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx
import pytest
import yaml

from arena import fetch_models as fm
from arena import openrouter
from arena.openrouter import OpenRouterUnavailable

ROOT = Path(__file__).resolve().parents[1]
REAL_CONFIG = ROOT / "config" / "models.yaml"


# --- 共用 fixture -----------------------------------------------------------


def _raw_payload() -> dict:
    """一份仿 OpenRouter 回應（含正常模型、變體、alias、動態定價）。"""
    return {
        "data": [
            {
                "id": "anthropic/claude-sonnet-4",
                "name": "Anthropic: Claude Sonnet 4",
                "context_length": 200000,
                "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            },
            {
                "id": "openai/gpt-5",
                "name": "OpenAI: GPT-5",
                "context_length": 400000,
                "pricing": {"prompt": "0.00000125", "completion": "0.00001"},
            },
            {
                "id": "deepseek/deepseek-chat-v3.1",
                "name": "DeepSeek: DeepSeek Chat V3.1",
                "context_length": 163840,
                "pricing": {"prompt": "0.00000025", "completion": "0.00000095"},
            },
            # 以下都不該進輸出
            {
                "id": "qwen/qwen3.8-27b:free",
                "name": "Qwen: Qwen3.8 27B (free)",
                "context_length": 131072,
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {
                "id": "openai/gpt-5:batch",
                "name": "OpenAI: GPT-5 (batch)",
                "context_length": 400000,
                "pricing": {"prompt": "0.0000005", "completion": "0.000004"},
            },
            {
                "id": "~openai/gpt-latest",
                "name": "OpenAI: GPT Latest",
                "context_length": 400000,
                "pricing": {"prompt": "0.000002", "completion": "0.00001"},
            },
            {
                "id": "typesafe/jev-router",
                "name": "Typesafe: JEV Router",
                "context_length": 1000000,
                "pricing": {"prompt": "-1", "completion": "-1"},
            },
            {
                # API 有、人工清單沒有（不該進輸出）
                "id": "meta-llama/llama-4-maverick",
                "name": "Meta: Llama 4 Maverick",
                "context_length": 1048576,
                "pricing": {"prompt": "0.0000001875", "completion": "0.0000006525"},
            },
        ]
    }


@pytest.fixture()
def api_models() -> dict[str, dict]:
    return openrouter.parse_models(_raw_payload())


@pytest.fixture()
def manual_config(tmp_path: Path) -> Path:
    """人工清單：3 個在 API 裡、1 個不在、1 個需靠 alias 命中。"""
    path = tmp_path / "models.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {"id": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4", "provider": "Anthropic"},
                    {"id": "openai/gpt-5", "name": "GPT-5", "provider": "OpenAI"},
                    # OpenRouter 沒有這個 id（示範缺欄標記）
                    {"id": "deepseek/deepseek-v3.1", "name": "DeepSeek V3.1", "provider": "DeepSeek"},
                    # alias 命中 API 的 deepseek/deepseek-chat-v3.1
                    {
                        "id": "deepseek/deepseek-chat",
                        "name": "DeepSeek Chat",
                        "provider": "DeepSeek",
                        "alias": "deepseek/deepseek-chat-v3.1",
                    },
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """預設把抓取換成必失敗，測試若需要資料必須自行覆寫。"""

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("測試不可真的打網路；請 mock fetch_models")

    monkeypatch.setattr(fm, "fetch_models", _boom)


# --- openrouter：純解析 -----------------------------------------------------


@pytest.mark.parametrize(
    ("model_id", "excluded"),
    [
        ("~openai/gpt-latest", True),
        ("qwen/qwen3.8-27b:free", True),
        ("openai/gpt-5:batch", True),
        ("anthropic/claude-sonnet-4", False),
        ("x-ai/grok-4.7", False),
    ],
)
def test_is_excluded(model_id: str, excluded: bool) -> None:
    assert openrouter.is_excluded(model_id) is excluded


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Anthropic: Claude Sonnet 4", "Claude Sonnet 4"),
        ("DeepSeek: DeepSeek V3.1", "DeepSeek V3.1"),
        ("openrouter/auto", "openrouter/auto"),
        ("  OpenAI: GPT-5  ", "GPT-5"),
    ],
)
def test_strip_provider_prefix(raw: str, expected: str) -> None:
    assert openrouter.strip_provider_prefix(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.000003", 3.0),
        ("0.000015", 15.0),
        ("0", 0.0),
        ("-1", None),
        (None, None),
        ("not-a-number", None),
    ],
)
def test_to_mtok(raw: object, expected: float | None) -> None:
    assert openrouter.to_mtok({"prompt": raw}, "prompt") == expected


def test_parse_models_filters_and_converts(api_models: dict[str, dict]) -> None:
    # 變體／alias 都被排除
    assert "qwen/qwen3.8-27b:free" not in api_models
    assert "openai/gpt-5:batch" not in api_models
    assert "~openai/gpt-latest" not in api_models

    sonnet = api_models["anthropic/claude-sonnet-4"]
    assert sonnet["name"] == "Claude Sonnet 4"
    assert sonnet["contextLength"] == 200000
    assert sonnet["priceUsdPerMTok"] == {"in": 3.0, "out": 15.0}

    # -1 動態定價視為無定價
    router = api_models["typesafe/jev-router"]
    assert router["priceUsdPerMTok"] == {"in": None, "out": None}


def test_parse_models_rejects_bad_payload() -> None:
    with pytest.raises(OpenRouterUnavailable):
        openrouter.parse_models(["not", "a", "dict"])
    with pytest.raises(OpenRouterUnavailable):
        openrouter.parse_models({"data": "not-a-list"})


# --- openrouter：I/O（MockTransport，不碰真實網路） ---------------------------


def test_fetch_models_with_mock_transport() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=_raw_payload())

    models = openrouter.fetch_models(
        transport=httpx.MockTransport(handler), attempts=1
    )

    assert captured["url"].startswith("https://openrouter.ai/api/v1/models")
    assert captured["params"].get("output_modalities") == "text"
    assert "anthropic/claude-sonnet-4" in models


def test_fetch_models_http_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="boom")

    with pytest.raises(OpenRouterUnavailable):
        openrouter.fetch_models(transport=httpx.MockTransport(handler), attempts=1)


# --- 人工清單載入 -----------------------------------------------------------


def test_load_real_config_is_valid() -> None:
    models = fm.load_manual_models(REAL_CONFIG)

    ids = [model["id"] for model in models]
    assert 6 <= len(models) <= 8
    assert len(ids) == len(set(ids))
    # 種子資料的 4 個模型必須在初始名單中
    for seed in [
        "anthropic/claude-sonnet-4",
        "openai/gpt-5",
        "google/gemini-2.5-pro",
        "deepseek/deepseek-v3.1",
    ]:
        assert seed in ids
    for model in models:
        assert model["name"]
        assert model["provider"]


def test_load_manual_models_rejects_duplicate_id(tmp_path: Path) -> None:
    path = tmp_path / "models.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {"id": "a/b", "name": "B", "provider": "A"},
                    {"id": "a/b", "name": "B again", "provider": "A"},
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="重複"):
        fm.load_manual_models(path)


def test_load_manual_models_rejects_missing_field(tmp_path: Path) -> None:
    path = tmp_path / "models.yaml"
    path.write_text(
        yaml.safe_dump({"models": [{"id": "a/b", "name": "B"}]}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="provider"):
        fm.load_manual_models(path)


# --- 合併：兩種關鍵情境 -----------------------------------------------------


def test_manual_only_model_is_kept_with_missing_marker(
    manual_config: Path, api_models: dict[str, dict]
) -> None:
    """人工清單有、API 沒有 → 仍要輸出，欄位留 None 並標記。"""
    manual = fm.load_manual_models(manual_config)
    merged = {model["id"]: model for model in fm.merge_models(manual, api_models)}

    absent = merged["deepseek/deepseek-v3.1"]
    assert absent["contextLength"] is None
    assert absent["priceUsdPerMTok"] is None
    assert absent["missing"] == ["contextLength", "priceUsdPerMTok"]
    # 人工欄位完整保留
    assert absent["name"] == "DeepSeek V3.1"
    assert absent["provider"] == "DeepSeek"


def test_api_only_model_is_not_in_output(
    manual_config: Path, api_models: dict[str, dict]
) -> None:
    """API 有、人工清單沒有 → 不該進輸出。"""
    manual = fm.load_manual_models(manual_config)
    output_ids = [model["id"] for model in fm.merge_models(manual, api_models)]

    assert "meta-llama/llama-4-maverick" not in output_ids
    assert set(output_ids) == {model["id"] for model in manual}
    # 輸出依 id 排序
    assert output_ids == sorted(output_ids)


def test_alias_is_used_as_fallback(
    manual_config: Path, api_models: dict[str, dict]
) -> None:
    manual = fm.load_manual_models(manual_config)
    merged = {model["id"]: model for model in fm.merge_models(manual, api_models)}

    aliased = merged["deepseek/deepseek-chat"]
    assert aliased["missing"] == []
    assert aliased["contextLength"] == 163840
    assert aliased["priceUsdPerMTok"] == {"in": 0.25, "out": 0.95}


def test_dynamic_pricing_marked_missing() -> None:
    manual = [{"id": "typesafe/jev-router", "name": "JEV Router", "provider": "Typesafe"}]
    api = openrouter.parse_models(_raw_payload())

    merged = fm.merge_models(manual, api)[0]
    assert merged["contextLength"] == 1000000
    assert merged["priceUsdPerMTok"] == {"in": None, "out": None}
    assert merged["missing"] == ["priceUsdPerMTok"]


# --- run：輸出、降級、可重現 ------------------------------------------------


def _run(tmp_path: Path, manual_config: Path) -> tuple[int, Path, str]:
    output = tmp_path / "models.json"
    args = argparse.Namespace(config=str(manual_config), output=str(output))
    code = fm.run(args)
    text = output.read_text(encoding="utf-8") if output.exists() else ""
    return code, output, text


def test_run_writes_merged_output(
    tmp_path: Path,
    manual_config: Path,
    api_models: dict[str, dict],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(fm, "fetch_models", lambda: api_models)

    code, output, text = _run(tmp_path, manual_config)
    document = json.loads(text)

    assert code == 0
    assert output.exists()
    assert document["meta"]["openrouterStatus"] == "ok"
    assert document["meta"]["modelsYamlHash"].startswith("sha256:")
    ids = [model["id"] for model in document["models"]]
    assert ids == sorted(ids)
    assert "meta-llama/llama-4-maverick" not in ids
    assert capsys.readouterr().out  # 有摘要輸出


def test_run_offline_keeps_manual_list_and_exits_zero(
    tmp_path: Path,
    manual_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fail() -> dict[str, dict]:
        raise OpenRouterUnavailable("模擬斷網")

    monkeypatch.setattr(fm, "fetch_models", _fail)

    code, output, text = _run(tmp_path, manual_config)
    document = json.loads(text)

    captured = capsys.readouterr()
    assert code == 0  # OpenRouter 掛掉仍算成功
    assert "OpenRouter 未取到資料" in captured.err
    assert document["meta"]["openrouterStatus"] == "unavailable"

    # 人工清單完整輸出
    manual = fm.load_manual_models(manual_config)
    assert [m["id"] for m in document["models"]] == sorted(m["id"] for m in manual)

    every_model = {m["id"]: m for m in document["models"]}
    assert every_model["anthropic/claude-sonnet-4"]["priceUsdPerMTok"] is None
    assert every_model["anthropic/claude-sonnet-4"]["missing"] == [
        "contextLength",
        "priceUsdPerMTok",
    ]
    assert every_model["openai/gpt-5"]["contextLength"] is None


def test_run_is_reproducible_except_fetched_at(
    tmp_path: Path,
    manual_config: Path,
    api_models: dict[str, dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fm, "fetch_models", lambda: api_models)

    timestamps = iter(["2026-09-29T01:00:00Z", "2026-09-29T02:30:00Z"])
    monkeypatch.setattr(fm, "_now_iso", lambda: next(timestamps))

    code_a, path_a, text_a = _run(tmp_path, manual_config)
    output_b = tmp_path / "models-b.json"
    args_b = argparse.Namespace(config=str(manual_config), output=str(output_b))
    code_b = fm.run(args_b)
    text_b = output_b.read_text(encoding="utf-8")

    assert code_a == code_b == 0
    doc_a = json.loads(text_a)
    doc_b = json.loads(text_b)

    # fetchedAt 不同
    assert doc_a["meta"]["fetchedAt"] != doc_b["meta"]["fetchedAt"]

    # 除 fetchedAt 外逐字相同（等同 jq 'del(.meta.fetchedAt)' 比較）
    del doc_a["meta"]["fetchedAt"]
    del doc_b["meta"]["fetchedAt"]
    assert json.dumps(doc_a, sort_keys=True) == json.dumps(doc_b, sort_keys=True)
    # 原始文字也只在 fetchedAt 那一行不同
    assert text_a.replace("2026-09-29T01:00:00Z", "") == text_b.replace(
        "2026-09-29T02:30:00Z", ""
    )


def test_run_missing_config_returns_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        config=str(tmp_path / "nope.yaml"), output=str(tmp_path / "out.json")
    )

    code = fm.run(args)

    assert code == fm.EXIT_CONFIG_ERROR
    assert "找不到人工清單" in capsys.readouterr().err


def test_run_uses_default_paths_when_attrs_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI 目前不注入 config／output，run 需以 getattr 走預設值。"""
    monkeypatch.chdir(tmp_path)
    # conftest 會把 DEFAULT_OUTPUT 導到暫存路徑；這裡還原真實預設以驗證預設邏輯。
    monkeypatch.setattr(fm, "DEFAULT_OUTPUT", Path("data/models.json"))
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "models.yaml").write_text(
        yaml.safe_dump({"models": [{"id": "a/b", "name": "B", "provider": "A"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(fm, "fetch_models", lambda: {})

    code = fm.run(argparse.Namespace())

    assert code == 0
    document = json.loads((tmp_path / "data" / "models.json").read_text(encoding="utf-8"))
    assert document["models"][0]["id"] == "a/b"
    assert document["meta"]["openrouterStatus"] == "ok"
