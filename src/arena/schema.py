"""schema v1 的 pydantic 定義（`arena validate` 的唯一依據）。

此檔是 `docs/plan.md`「資料契約（schema v1）」的可執行版本：欄位一律以計畫為準，
不自行增減。若計畫的 schema 有歧義或需要變更，先改 `docs/plan.md` 再改這裡，
因為這份契約同時被 `jason-lab` 網站端依賴。

兩種檔案：

- ``data/scores.json``       → :class:`ScoresDocument`
- ``data/evidence/*.jsonl``  → 每行一筆 :class:`EvidenceRecord`
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# 資料契約版本；`meta.schemaVersion` 固定為此值。
SCHEMA_VERSION = 1

# evidence 參照格式：`<路徑>.jsonl#l<行號>`。
# 目錄前綴可省略，所以計畫範例 "evidence/2026-09-29.jsonl#l1204" 與
# 種子資料的 "sample.jsonl#l1" 都合法。
EVIDENCE_REF_PATTERN = r"^(?:[^#\s/]+/)*[^#\s/]+\.jsonl#l[1-9][0-9]*$"

# 態度標籤：正面／負面／中立。
Label = Literal["positive", "negative", "neutral"]

# 帶格式檢查的 evidence 參照字串。
EvidenceRef = Annotated[str, StringConstraints(pattern=EVIDENCE_REF_PATTERN)]


class _ContractModel(BaseModel):
    """所有契約模型的共同設定：拒絕未定義欄位，避免打錯字靜默通過。"""

    model_config = ConfigDict(extra="forbid")


class JudgeInfo(_ContractModel):
    """評分器資訊。"""

    model: str = Field(min_length=1, description="評分器模型名稱，例如 laya")
    revision: str = Field(min_length=1, description="評分器版本或 commit sha")
    calibrated: bool = Field(description="是否已通過校準驗證")


class Meta(_ContractModel):
    """``scores.json`` 的詮釋資料。"""

    schemaVersion: Literal[1] = Field(description="資料契約版本，固定為 1")
    generatedAt: datetime = Field(description="產出時間（ISO 8601）")
    windowDays: int = Field(ge=1, description="取樣窗口天數")
    kind: Literal["community-sentiment"] = Field(
        description="資料種類，明確標示這不是 benchmark"
    )
    disclaimer: str = Field(min_length=1, description="對外顯示的免責聲明")
    judge: JudgeInfo
    notes: str = Field(description="補充說明，例如窗口偏誤或種子資料標記")


class PriceUsdPerMTok(_ContractModel):
    """每百萬 token 的美元價格。

    欄位名 ``in`` 是 Python 關鍵字，故用 ``price_in``／``price_out`` 搭配 alias，
    JSON 端仍為 ``{"in": ..., "out": ...}``。
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    price_in: float = Field(alias="in", ge=0, description="輸入 token 單價（美元／百萬 token）")
    price_out: float = Field(alias="out", ge=0, description="輸出 token 單價（美元／百萬 token）")


class Dimensions(_ContractModel):
    """三個維度的分數（0～100）與定價。"""

    quality: float = Field(ge=0, le=100, description="品質分數")
    speed: float = Field(ge=0, le=100, description="速度分數")
    price: float = Field(ge=0, le=100, description="價格 CP 值分數")
    priceUsdPerMTok: PriceUsdPerMTok


class ModelEntry(_ContractModel):
    """單一模型的社群評價結果。"""

    id: str = Field(min_length=1, description="模型識別碼，例如 anthropic/claude-sonnet-4")
    name: str = Field(min_length=1, description="顯示名稱")
    provider: str = Field(min_length=1, description="廠牌，供網站篩選")
    score: float = Field(ge=0, le=100, description="總分")
    dimensions: Dimensions
    sampleSize: int = Field(ge=0, description="樣本數（正面＋負面＋中立的提及總數）")
    positiveRate: float = Field(ge=0, le=1, description="正面提及比例")
    confidence: float = Field(ge=0, le=1, description="信心值")
    mentionsBySource: dict[str, int] = Field(description="各來源的提及次數，例如 reddit／x／hn")
    evidence: list[EvidenceRef] = Field(description="指向 evidence jsonl 的參照清單")
    updatedAt: datetime = Field(description="此列資料的更新時間（ISO 8601）")


class ScoresDocument(_ContractModel):
    """``data/scores.json`` 的完整結構。"""

    meta: Meta
    models: list[ModelEntry]


class EvidenceRecord(_ContractModel):
    """``data/evidence/YYYY-MM-DD.jsonl`` 的每一行。"""

    hash: str = Field(min_length=1, description="去重鍵（正規化內容的 hash）")
    modelId: str = Field(min_length=1, description="對應 scores.json 的 model id")
    source: str = Field(min_length=1, description="來源，例如 reddit／x／hn")
    url: str = Field(min_length=1, description="原文連結")
    # 允許 null（plan.md 實作裁定第 6 條）：last30days 的 agent JSON 無 author 欄、
    # raw profile 也只有部分有；C2 會盡量以公開 API 回填，補不到時留 null。
    author: str | None = Field(
        default=None, min_length=1, description="原作者；補不到時為 null"
    )
    postedAt: datetime = Field(description="張貼時間（ISO 8601）")
    text: str = Field(min_length=1, description="貼文內容")
    # 以下三欄由 C2 落地時先寫 null，交由 C3 `arena score` 回填；
    # 因此「結構合法但尚未評分」是合法的 evidence（plan.md 實作裁定第 7 條）。
    label: Label | None = Field(default=None, description="評分器的態度標籤；未評分為 null")
    prob: float | None = Field(
        default=None, ge=0, le=1, description="評分器給的校準機率；未評分為 null"
    )
    judge: str | None = Field(
        default=None, min_length=1, description="評分器與版本，例如 laya@<sha>；未評分為 null"
    )


__all__ = [
    "SCHEMA_VERSION",
    "EVIDENCE_REF_PATTERN",
    "EvidenceRecord",
    "ScoresDocument",
    "ModelEntry",
    "Meta",
    "JudgeInfo",
    "Dimensions",
    "PriceUsdPerMTok",
]
