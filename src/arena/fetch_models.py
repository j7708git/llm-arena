"""`arena fetch-models` 的實作（任務 C1）。

合併「人工維護的模型清單」（``config/models.yaml``，主）與「OpenRouter
`/api/v1/models` 的定價／context length」（附掛欄位），產出中間檔
``data/models.json`` 供後續任務（C4 build）使用。

設計重點：

- **人工清單是主**：輸出只含人工名單中的模型；OpenRouter 有、人工沒有的一律
  不進輸出。
- **API 只是附掛**：OpenRouter 掛掉時不影響人工清單，缺的欄位放 ``None`` 並在
  ``missing`` 陣列標記，``run`` 仍回 0（僅在 stderr 說明）。
- **可重現**：``models`` 依 id 排序、JSON 以 ``sort_keys=True`` 與固定 indent
  輸出，除 ``meta.fetchedAt`` 外逐字可重現。驗證方式：

      .venv/bin/arena fetch-models && cp data/models.json /tmp/a.json
      .venv/bin/arena fetch-models
      diff <(jq 'del(.meta.fetchedAt)' /tmp/a.json) \
           <(jq 'del(.meta.fetchedAt)' data/models.json)

選用參數（``--config``／``--output``）以屬性方式由 ``args`` 讀取，缺省時走
``config/models.yaml`` 與 ``data/models.json``。CLI 端（``arena.cli``）目前不
注入這兩個屬性，故一律以 :func:`getattr` 取預設值；測試或程式呼叫可直接傳入
帶有 ``config``／``output`` 屬性的 ``argparse.Namespace``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from arena.openrouter import OpenRouterUnavailable, fetch_models

# 預設路徑（相對於執行時的工作目錄）。
DEFAULT_CONFIG = Path("config/models.yaml")
DEFAULT_OUTPUT = Path("data/models.json")

# 人工清單／輸出檔問題時的結束碼；與「OpenRouter 掛掉仍成功（0）」區分。
EXIT_CONFIG_ERROR = 1

# OpenRouter 成功／失敗的 meta 狀態字串。
STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"

# OpenRouter 查不到模型時，哪些欄位會缺漏（順序固定，保證可重現）。
MISSING_WHEN_ABSENT = ["contextLength", "priceUsdPerMTok"]


def _now_iso() -> str:
    """目前 UTC 時間，格式 ``YYYY-MM-DDTHH:MM:SSZ``（唯一會變的欄位）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_of(path: Path) -> str:
    """回傳檔案的 ``sha256:<hex>``，用來記錄人工清單的版本。"""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def load_manual_models(path: Path | str) -> list[dict]:
    """讀取人工維護清單。

    回傳 ``[{id, name, provider, alias?}, ...]``；缺欄位、型別錯、id 重複時
    丟 :class:`ValueError` 並帶明確原因。
    """
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"找不到人工清單：{path}") from None
    except yaml.YAMLError as exc:
        raise ValueError(f"人工清單 YAML 解析失敗：{path}：{exc}") from None

    if not isinstance(raw, dict) or not isinstance(raw.get("models"), list):
        raise ValueError(f"人工清單格式錯誤：{path}：最上層需為含 models 陣列的物件")

    models: list[dict] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw["models"]):
        where = f"{path}:models[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"人工清單格式錯誤：{where}：需為物件")

        model_id = entry.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError(f"人工清單格式錯誤：{where}：缺少非空的 id")
        model_id = model_id.strip()

        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"人工清單格式錯誤：{where}：{model_id} 缺少非空的 name")

        provider = entry.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError(
                f"人工清單格式錯誤：{where}：{model_id} 缺少非空的 provider"
            )

        if model_id in seen:
            raise ValueError(f"人工清單格式錯誤：{where}：id 重複：{model_id}")
        seen.add(model_id)

        record: dict = {
            "id": model_id,
            "name": name.strip(),
            "provider": provider.strip(),
        }
        alias = entry.get("alias")
        if alias is not None:
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError(
                    f"人工清單格式錯誤：{where}：{model_id} 的 alias 需為非空字串"
                )
            record["alias"] = alias.strip()
        models.append(record)

    if not models:
        raise ValueError(f"人工清單是空的：{path}")

    return models


def _missing_for(record: dict | None) -> list[str]:
    """依 OpenRouter 記錄內容回傳缺漏欄位清單（找不到模型時為全部附掛欄位）。"""
    if record is None:
        return list(MISSING_WHEN_ABSENT)

    missing: list[str] = []
    if record.get("contextLength") is None:
        missing.append("contextLength")
    price = record.get("priceUsdPerMTok")
    if not isinstance(price, dict) or price.get("in") is None or price.get("out") is None:
        missing.append("priceUsdPerMTok")
    return missing


def merge_models(manual: list[dict], api: dict[str, dict]) -> list[dict]:
    """以 id 為鍵合併人工清單與 OpenRouter 記錄（只輸出人工名單中的模型）。

    查得到 id 就用；查不到時改用選用的 ``alias`` 再查一次。OpenRouter 沒有或
    欄位缺漏時，該欄位放 ``None`` 並列入 ``missing``。輸出依 id 排序。
    """
    merged: list[dict] = []
    for entry in sorted(manual, key=lambda item: item["id"]):
        model_id = entry["id"]
        record = api.get(model_id)
        if record is None and entry.get("alias"):
            record = api.get(entry["alias"])

        merged.append(
            {
                "id": model_id,
                "name": entry["name"],
                "provider": entry["provider"],
                "contextLength": None if record is None else record.get("contextLength"),
                "priceUsdPerMTok": (
                    None if record is None else record.get("priceUsdPerMTok")
                ),
                "missing": _missing_for(record),
            }
        )
    return merged


def build_document(
    manual: list[dict],
    api: dict[str, dict],
    *,
    fetched_at: str,
    models_yaml_hash: str,
    status: str = STATUS_OK,
    source: str = "openrouter",
) -> dict:
    """組出 ``data/models.json`` 的完整結構。"""
    return {
        "meta": {
            "fetchedAt": fetched_at,
            "source": source,
            "openrouterStatus": status,
            "modelsYamlHash": models_yaml_hash,
        },
        "models": merge_models(manual, api),
    }


def _dump(document: dict) -> str:
    """序列化：``sort_keys`` + 固定 indent 2，保證除 fetchedAt 外逐字可重現。"""
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def run(args: argparse.Namespace) -> int:
    """更新模型清單與定價（任務 C1）。成功（含 OpenRouter 掛掉）回 0。"""
    config_path = Path(getattr(args, "config", None) or DEFAULT_CONFIG)
    output_path = Path(getattr(args, "output", None) or DEFAULT_OUTPUT)

    try:
        manual = load_manual_models(config_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"fetch-models：{exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    status = STATUS_OK
    api: dict[str, dict] = {}
    try:
        api = fetch_models()
    except OpenRouterUnavailable as exc:
        status = STATUS_UNAVAILABLE
        print(
            f"fetch-models：OpenRouter 未取到資料（{exc}）。\n"
            "  將只輸出人工清單，並在缺漏欄位標記 missing。",
            file=sys.stderr,
        )

    document = build_document(
        manual,
        api,
        fetched_at=_now_iso(),
        models_yaml_hash=_sha256_of(config_path),
        status=status,
    )

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_dump(document), encoding="utf-8")
    except OSError as exc:
        print(f"fetch-models：無法寫入 {output_path}：{exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    incomplete = sum(1 for model in document["models"] if model["missing"])
    match_note = (
        f"OpenRouter：{'已連線' if status == STATUS_OK else '未取到（unavailable）'}"
    )
    print(
        f"fetch-models：寫入 {output_path}（{len(document['models'])} 個模型，"
        f"其中 {incomplete} 個有缺漏欄位；{match_note}）。"
    )
    return 0


__all__ = [
    "DEFAULT_CONFIG",
    "DEFAULT_OUTPUT",
    "EXIT_CONFIG_ERROR",
    "load_manual_models",
    "merge_models",
    "build_document",
    "run",
]
