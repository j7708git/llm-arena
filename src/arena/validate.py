"""`arena validate` 的實作：讀檔、依副檔名分流、把 pydantic 錯誤轉成人類可讀訊息。

設計重點：

- ``.json``  → 視為 ``scores.json``，套用 :class:`~arena.schema.ScoresDocument`
- ``.jsonl`` → 視為 evidence，逐行套用 :class:`~arena.schema.EvidenceRecord`
- 錯誤訊息一律帶「檔案 + 位置（model index／jsonl 行號）+ 欄位」，不噴 raw traceback。
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from arena.schema import (
    EvidenceRecord,
    EvidenceRecordV12,
    ScoresDocument,
    dimension_key_errors,
)

EXIT_OK = 0
EXIT_INVALID = 1

# pydantic 錯誤類型 → 中文提示。沒對應到的用預設字樣。
_ERROR_HINTS: dict[str, str] = {
    "missing": "缺少必要欄位",
    "extra_forbidden": "出現 schema 未定義的欄位",
    "literal_error": "欄位值不在允許清單",
    "greater_than_equal": "數值低於允許下限",
    "greater_than": "數值低於允許下限",
    "less_than_equal": "數值高於允許上限",
    "less_than": "數值高於允許上限",
    "int_type": "型別錯誤，必須是整數",
    "int_parsing": "型別錯誤，必須是整數",
    "float_type": "型別錯誤，必須是數字",
    "float_parsing": "型別錯誤，必須是數字",
    "string_type": "型別錯誤，必須是字串",
    "bool_type": "型別錯誤，必須是布林值",
    "bool_parsing": "型別錯誤，必須是布林值",
    "list_type": "型別錯誤，必須是陣列",
    "dict_type": "型別錯誤，必須是物件",
    "datetime_type": "型別錯誤，必須是 ISO 8601 日期時間字串",
    "datetime_parsing": "日期時間格式無法解析（需 ISO 8601）",
    "datetime_from_date_parsing": "日期時間格式無法解析（需 ISO 8601）",
    "string_too_short": "字串長度不足",
    "string_pattern_mismatch": "字串格式不符",
}

_DEFAULT_HINT = "欄位驗證失敗"


def _format_location(loc: tuple[object, ...]) -> str:
    """把 pydantic 的 loc tuple 轉成 ``models[0].score`` 這種位置字串。"""
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        elif parts:
            parts.append(f".{item}")
        else:
            parts.append(str(item))
    return "".join(parts)


def _describe_error(error: dict[str, object]) -> str:
    """把單一 pydantic 錯誤轉成「位置：中文提示（原始 msg）」。"""
    location = _format_location(tuple(error.get("loc", ())))  # type: ignore[arg-type]
    hint = _ERROR_HINTS.get(str(error.get("type", "")), _DEFAULT_HINT)
    raw_msg = str(error.get("msg", ""))
    detail = f"{hint}（{raw_msg}）" if raw_msg else hint
    return f"{location}：{detail}" if location else detail


def _errors_from_validation(exc: ValidationError) -> list[str]:
    return [_describe_error(error) for error in exc.errors()]


def validate_scores_data(data: object) -> list[str]:
    """驗證已解析的 scores 物件；回傳錯誤訊息清單（合法則為空）。

    pydantic 驗證過後再跑一道跨欄位交叉檢查：``models[].dimensions`` 的鍵必須恰好
    等於 ``meta.dimensions`` 宣告的 id 集合（實作裁定第 9 條）。
    """
    try:
        document = ScoresDocument.model_validate(data)
    except ValidationError as exc:
        return _errors_from_validation(exc)
    return dimension_key_errors(document)


def _evidence_model_for(payload: dict):
    """依內容挑 evidence 的 schema 版本（實作裁定 12）。

    evidence 每行沒有版本欄位，因此以「有沒有 ``juryVotes``」或
    「``judge`` 是否為 ``llm-jury@``」判斷是否為 v1.2 評審團版；否則用 v1.1。
    """
    judge = payload.get("judge")
    if "juryVotes" in payload or (
        isinstance(judge, str) and judge.startswith("llm-jury@")
    ):
        return EvidenceRecordV12
    return EvidenceRecord


def validate_evidence_lines(text: str) -> list[str]:
    """逐行驗證 evidence jsonl；回傳錯誤訊息清單（合法則為空）。

    空行會被略過；每條訊息帶上第幾行。每行依內容分 v1.1／v1.2 schema
    （:func:`_evidence_model_for`）。
    """
    errors: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(
                f"第 {line_number} 行：JSON 解析失敗：{exc.msg}（第 {exc.colno} 欄）"
            )
            continue
        if not isinstance(payload, dict):
            errors.append(f"第 {line_number} 行：每行必須是 JSON 物件")
            continue
        model = _evidence_model_for(payload)
        try:
            model.model_validate(payload)
        except ValidationError as exc:
            for message in _errors_from_validation(exc):
                errors.append(f"第 {line_number} 行：{message}")
    return errors


def validate_path(path: Path | str) -> list[str]:
    """驗證單一檔案；回傳錯誤訊息清單（合法則為空）。

    ``.json`` 當成 scores.json、``.jsonl`` 當成 evidence；其他副檔名視為錯誤。
    """
    path = Path(path)

    if not path.exists():
        return [f"{path}：找不到檔案"]
    if path.is_dir():
        return [f"{path}：這是一個目錄，請指定檔案"]

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}：無法讀取檔案：{exc}"]
    except UnicodeDecodeError:
        return [f"{path}：不是 UTF-8 文字檔"]

    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return [f"{path}：{message}" for message in validate_evidence_lines(text)]
    if suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return [
                f"{path}：JSON 解析失敗：{exc.msg}（第 {exc.lineno} 行第 {exc.colno} 欄）"
            ]
        return [f"{path}：{message}" for message in validate_scores_data(data)]

    return [f"{path}：不支援的副檔名 '{suffix}'（支援 .json 與 .jsonl）"]
