"""OpenRouter `/api/v1/models` 的抓取與解析（任務 C1）。

依 OpenRouter 公開 API 的實測規則處理（端點與定價的用途見 `docs/plan.md` §2「管線概觀」）：

- 端點公開、免 key；一次抓回全部 text 模型（預設 `output_modalities=text`）。
- 定價是 **USD／per token 的字串**，換成 schema 的 ``priceUsdPerMTok`` 要 ×1e6。
- 負值（`-1`）代表動態／router 定價，不是真價格，必須視為「無定價」。
- 排除 `~` 開頭的 alias 與含 `:` 的變體（`:free`／`:batch`），避免同模型重複計價。
- `name` 形如 ``"Anthropic: Claude Sonnet 4"``，要去掉 ``"<provider>: "`` 前綴。

本模組只負責「抓 + 解析成乾淨的 dict」；與人工清單的合併邏輯在
:mod:`arena.fetch_models`。抓取失敗一律丟 :class:`OpenRouterUnavailable`，
讓呼叫端能降級成「人工清單 + 缺欄標記」，不讓整條管線失敗。
"""

from __future__ import annotations

import time
from typing import Any

import httpx

# 模型清單端點（免 key）。定價／context 的附掛見 docs/plan.md §2。
MODELS_URL = "https://openrouter.ai/api/v1/models"

# 單次請求逾時（秒）。回應約 750 KB，15 秒足夠。
DEFAULT_TIMEOUT = 15.0

# 失敗重試次數與退避秒數（R2 建議重試 2~3 次再放棄）。
DEFAULT_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 0.5


class OpenRouterUnavailable(RuntimeError):
    """OpenRouter 模型清單取不到（網路錯誤／非 2xx／回應不是預期 JSON）。"""


def is_excluded(model_id: str) -> bool:
    """是否為要排除的 alias（``~``）或變體（含 ``:``，如 ``:free``／``:batch``）。"""
    return model_id.startswith("~") or ":" in model_id


def strip_provider_prefix(name: str) -> str:
    """去掉 ``name`` 的 ``"<provider>: "`` 前綴。

    ``"Anthropic: Claude Sonnet 4"`` → ``"Claude Sonnet 4"``；沒有前綴的
    （例如 ``openrouter/auto``）原樣回傳。
    """
    prefix, sep, rest = name.partition(": ")
    if sep and rest.strip():
        return rest.strip()
    return name.strip()


def to_mtok(pricing: dict[str, Any], key: str) -> float | None:
    """把 ``pricing[key]``（USD/token 字串）換成 USD/百萬 token。

    缺值、非數字、或負值（``-1`` 動態定價）一律回 ``None``。
    """
    raw = pricing.get(key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value * 1_000_000


def parse_models(payload: object) -> dict[str, dict]:
    """把 ``/api/v1/models`` 的回應解析成 ``{id: record}``。

    ``record`` 含 ``id``／``name``（已剝前綴）／``contextLength``／
    ``priceUsdPerMTok``。排除 alias 與變體。結構不符時丟
    :class:`OpenRouterUnavailable`。
    """
    if not isinstance(payload, dict):
        raise OpenRouterUnavailable("OpenRouter 回應不是物件")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise OpenRouterUnavailable("OpenRouter 回應缺少 data 陣列")

    parsed: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = row.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        if is_excluded(model_id):
            continue

        raw_name = row.get("name")
        name = strip_provider_prefix(raw_name) if isinstance(raw_name, str) else model_id

        context_length = row.get("context_length")
        if not isinstance(context_length, int) or isinstance(context_length, bool):
            context_length = None

        pricing = row.get("pricing")
        if not isinstance(pricing, dict):
            pricing = {}

        parsed[model_id] = {
            "id": model_id,
            "name": name,
            "contextLength": context_length,
            "priceUsdPerMTok": {
                "in": to_mtok(pricing, "prompt"),
                "out": to_mtok(pricing, "completion"),
            },
        }
    return parsed


def fetch_models(
    url: str = MODELS_URL,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    attempts: int = DEFAULT_ATTEMPTS,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, dict]:
    """抓取並解析 OpenRouter 模型清單。

    失敗（網路錯誤／非 2xx／JSON 解析失敗）會重試 ``attempts`` 次，仍失敗則丟
    :class:`OpenRouterUnavailable`。``transport`` 供測試注入（不真的打網路）。
    """
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=timeout, transport=transport) as client:
                response = client.get(url, params={"output_modalities": "text"})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(RETRY_BACKOFF_SECONDS)
            continue
        return parse_models(payload)

    raise OpenRouterUnavailable(f"OpenRouter 模型清單取不到：{last_error}")


__all__ = [
    "MODELS_URL",
    "DEFAULT_TIMEOUT",
    "OpenRouterUnavailable",
    "is_excluded",
    "strip_provider_prefix",
    "to_mtok",
    "parse_models",
    "fetch_models",
]
