"""schema v1.1 的 pydantic 定義（`arena validate` 的唯一依據）。

此檔是 `docs/plan.md`「資料契約（schema v1.1）」的可執行版本：欄位一律以計畫為準，
不自行增減。若計畫的 schema 有歧義或需要變更，先改 `docs/plan.md` 再改這裡，
因為這份契約同時被 `jason-lab` 網站端依賴。

v1.1（2026-09-29）相對 v1 的變化：

- evidence 的單筆 ``label``／``prob`` 改成 ``votes``：一次 laya pass 問六題
  （``overall`` ＋ 五個面向），每題回 ``{label, prob}``。未評分時 ``votes`` 為 null。
- ``overall`` 的標籤是 ``positive``／``negative``／``neutral``；五個面向維度的標籤是
  ``positive``／``negative``／``not-discussed``（「這則沒談該面向」不同於「談了但中立」，
  見實作裁定第 8 條）。
- ``scores.json`` 的 ``meta`` 新增 ``dimensions``（站方表格欄位由它驅動）、``weights``
  （總分權重）、``sourcesCovered``；``models[].dimensions`` 成為開放 map
  （值 0～100 或 null），鍵必須恰好等於 ``meta.dimensions`` 宣告的 id 集合
  （交叉檢查見 :func:`dimension_key_errors`，實作裁定第 9 條）；
  ``priceUsdPerMTok`` 移到 model 層級；新增 ``dimensionSamples``。

兩種檔案：

- ``data/scores.json``       → :class:`ScoresDocument`
- ``data/evidence/*.jsonl``  → 每行一筆 :class:`EvidenceRecord`
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# 資料契約版本；`meta.schemaVersion` 固定為此值。
SCHEMA_VERSION = 1.1

# evidence 參照格式：`<路徑>.jsonl#l<行號>`。
# 目錄前綴可省略，所以計畫範例 "evidence/2026-09-29.jsonl#l1204" 與
# 種子資料的 "sample.jsonl#l1" 都合法。
EVIDENCE_REF_PATTERN = r"^(?:[^#\s/]+/)*[^#\s/]+\.jsonl#l[1-9][0-9]*$"

# --- 維度與投票（v1.1）-----------------------------------------------------
# 一次 laya pass 問六題：overall（總評）＋五個面向維度。v1.1 的面向固定為這五個，
# 之後新增維度（前端／後端／財務適合度…）屬 schema 變更：要同步改這裡、score 的
# rubric、`meta.dimensions`，並在 `docs/plan.md` 記錄。
OVERALL_VOTE_ID = "overall"
FACET_DIMENSION_IDS: tuple[str, ...] = (
    "quality",
    "speed",
    "tokenEfficiency",
    "tokenUsage",
    "priceValue",
)
# votes 的鍵集合（= overall ＋ 五面向），順序即 rubric 的呈現順序。
VOTE_IDS: tuple[str, ...] = (OVERALL_VOTE_ID, *FACET_DIMENSION_IDS)

# 總分權重（`meta.weights`）的 v1.1 預設值：面向 id → 0～1。
DEFAULT_WEIGHTS: dict[str, float] = {
    "quality": 0.5,
    "speed": 0.2,
    "tokenEfficiency": 0.05,
    "tokenUsage": 0.05,
    "priceValue": 0.2,
}

# 態度標籤：overall 用 positive／negative／neutral，面向維度用 positive／negative／
# not-discussed（neutral 不適用於面向，not-discussed 不適用於 overall）。
OverallLabel = Literal["positive", "negative", "neutral"]
FacetLabel = Literal["positive", "negative", "not-discussed"]

# 機率：0～1。
Probability = Annotated[float, Field(ge=0, le=1)]
# 維度分數：非 null 時 0～100。
DimensionScore = Annotated[float, Field(ge=0, le=100)]
# 樣本數：整數、>= 0。
SampleCount = Annotated[int, Field(ge=0)]

# 帶格式檢查的 evidence 參照字串。
EvidenceRef = Annotated[str, StringConstraints(pattern=EVIDENCE_REF_PATTERN)]


class _ContractModel(BaseModel):
    """所有契約模型的共同設定：拒絕未定義欄位，避免打錯字靜默通過。"""

    model_config = ConfigDict(extra="forbid")


class JudgeInfo(_ContractModel):
    """評分器資訊。"""

    model: str = Field(min_length=1, description="評分器模型名稱，例如 laya")
    revision: str = Field(min_length=1, description="評分器版本或 commit sha")
    calibrated: bool = Field(description="是否已通過校準驗證（語意是「已通過 C5 校準」）")


class DimensionSpec(_ContractModel):
    """`meta.dimensions` 的一筆：站方表格欄位的宣告（順序即欄位順序）。"""

    id: str = Field(min_length=1, description="面向 id，例如 quality")
    label: str = Field(min_length=1, description="站方顯示名稱，例如 智能")


class Meta(_ContractModel):
    """``scores.json`` 的詮釋資料。"""

    schemaVersion: Literal[1.1] = Field(description="資料契約版本，固定為 1.1")
    generatedAt: datetime = Field(description="產出時間（ISO 8601）")
    windowDays: int = Field(ge=1, description="取樣窗口天數")
    kind: Literal["community-sentiment"] = Field(
        description="資料種類，明確標示這不是 benchmark"
    )
    disclaimer: str = Field(min_length=1, description="對外顯示的免責聲明")
    judge: JudgeInfo
    # 站方表格欄位由這裡驅動，之後加維度不必改前端（見實作裁定 9）。
    dimensions: list[DimensionSpec] = Field(
        min_length=1, description="面向維度宣告（id／label），站方表格欄位的來源"
    )
    # 總分權重（面向 id → 0～1），build 讀它；只計非 null 維度後重歸一。
    weights: dict[str, Probability] = Field(description="各面向的總分權重")
    # 涵蓋徽章（R3 偏誤標示），非空字串陣列。
    sourcesCovered: list[Annotated[str, Field(min_length=1)]] = Field(
        min_length=1, description="本檔涵蓋的來源，例如 reddit／hn"
    )
    notes: str = Field(description="補充說明，例如窗口偏誤或種子資料標記")


class PriceUsdPerMTok(_ContractModel):
    """每百萬 token 的美元價格。

    欄位名 ``in`` 是 Python 關鍵字，故用 ``price_in``／``price_out`` 搭配 alias，
    JSON 端仍為 ``{"in": ..., "out": ...}``。``models.json`` 查無定價時可為 null
    （整個物件或個別欄位皆可，見實作裁定第 1 條）。
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    price_in: float | None = Field(
        default=None, alias="in", ge=0, description="輸入 token 單價（美元／百萬 token）"
    )
    price_out: float | None = Field(
        default=None, alias="out", ge=0, description="輸出 token 單價（美元／百萬 token）"
    )


class ModelEntry(_ContractModel):
    """單一模型的社群評價結果。"""

    id: str = Field(min_length=1, description="模型識別碼，例如 anthropic/claude-sonnet-4")
    name: str = Field(min_length=1, description="顯示名稱")
    provider: str = Field(min_length=1, description="廠牌，供網站篩選")
    score: float = Field(ge=0, le=100, description="總分（weights 加權，null 維度剔除後重歸一）")
    # 開放 map（值 0～100 或 null）；鍵必須恰好等於 meta.dimensions 宣告的 id 集合。
    # 沒有討論（P+N=0）的維度是 null，站方顯示「資料不足」，不得顯示成 50。
    dimensions: dict[str, DimensionScore | None] = Field(
        description="各面向分數（0～100）或 null（資料不足）"
    )
    # 硬資料，來自 models.json，非態度；查無定價時為 null。
    priceUsdPerMTok: PriceUsdPerMTok | None = Field(
        default=None, description="每百萬 token 美元定價；查無為 null"
    )
    # 各面向「有表態」的樣本數（面向 id → 非負整數）。
    dimensionSamples: dict[str, SampleCount] = Field(
        description="各面向的樣本數（面向 id → 非負整數）"
    )
    sampleSize: int = Field(ge=0, description="樣本數（該模型全部 evidence 筆數）")
    positiveRate: float = Field(ge=0, le=1, description="overall（總評）的正面率")
    confidence: float = Field(ge=0, le=1, description="信心值")
    mentionsBySource: dict[str, int] = Field(description="各來源的提及次數，例如 reddit／hn")
    evidence: list[EvidenceRef] = Field(description="指向 evidence jsonl 的參照清單")
    updatedAt: datetime = Field(description="此列資料的更新時間（ISO 8601）")


class ScoresDocument(_ContractModel):
    """``data/scores.json`` 的完整結構。"""

    meta: Meta
    models: list[ModelEntry]


class OverallVote(_ContractModel):
    """總評的一票：positive／negative／neutral。"""

    label: OverallLabel
    prob: Probability = Field(description="校準機率；一律取 laya 的 answer_confidence")


class FacetVote(_ContractModel):
    """單一面向的一票：positive／negative／not-discussed。"""

    label: FacetLabel
    prob: Probability = Field(description="校準機率；一律取 laya 的 answer_confidence")


class Votes(_ContractModel):
    """一次 pass 的六題投票結果。

    鍵固定為 ``overall`` ＋五個面向 id（`VOTE_IDS`），每值 ``{label, prob}``；
    ``extra="forbid"`` 讓缺鍵／多鍵都在 validate 時被指名。
    """

    overall: OverallVote
    quality: FacetVote
    speed: FacetVote
    tokenEfficiency: FacetVote
    tokenUsage: FacetVote
    priceValue: FacetVote


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
    # 以下兩欄由 C2 落地時先寫 null，交由 C3 `arena score` 回填；
    # 因此「結構合法但尚未評分」是合法的 evidence（plan.md 實作裁定第 7 條）。
    votes: Votes | None = Field(
        default=None, description="六題投票（overall＋五面向）；未評分為 null"
    )
    judge: str | None = Field(
        default=None, min_length=1, description="評分器與版本，例如 laya@<sha>；未評分為 null"
    )


def dimension_key_errors(document: ScoresDocument) -> list[str]:
    """交叉檢查 `models[].dimensions` 的鍵是否等於 `meta.dimensions` 宣告的 id 集合。

    回傳錯誤訊息清單（合法則為空），位置帶 model index（例如 ``models[0].dimensions``）。
    pydantic 的型別／值域驗證擋不住「鍵不對」，所以另做這道檢查（實作裁定第 9 條）。
    """
    declared = [spec.id for spec in document.meta.dimensions]
    allowed = set(declared)
    errors: list[str] = []

    for index, model in enumerate(document.models):
        keys = set(model.dimensions)
        missing = sorted(allowed - keys)
        unknown = sorted(keys - allowed)
        if not missing and not unknown:
            continue
        details: list[str] = []
        if missing:
            details.append("缺少 " + "、".join(missing))
        if unknown:
            details.append("多出 " + "、".join(unknown))
        errors.append(
            f"models[{index}].dimensions：鍵必須恰好等於 meta.dimensions 宣告的 id"
            f"（{'；'.join(details)}）"
        )
    return errors


__all__ = [
    "SCHEMA_VERSION",
    "EVIDENCE_REF_PATTERN",
    "OVERALL_VOTE_ID",
    "FACET_DIMENSION_IDS",
    "VOTE_IDS",
    "DEFAULT_WEIGHTS",
    "EvidenceRecord",
    "ScoresDocument",
    "ModelEntry",
    "Meta",
    "JudgeInfo",
    "DimensionSpec",
    "Votes",
    "OverallVote",
    "FacetVote",
    "PriceUsdPerMTok",
    "dimension_key_errors",
]
