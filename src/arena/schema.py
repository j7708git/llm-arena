"""schema v1.1／v1.2 的 pydantic 定義（`arena validate` 的唯一依據）。

此檔是 `docs/plan.md`「資料契約」與「Schema 實作裁定」的可執行版本：欄位一律以計畫為準，
不自行增減。若計畫的 schema 有歧義或需要變更，先改 `docs/plan.md` 再改這裡，
因為這份契約同時被 `jason-lab` 網站端依賴。

**版本處理（C8，2026-09-30）**：`validate` 同時接受 v1.1 與 v1.2 兩種形狀，
依內容分版本（實作裁定第 12 條）：

- `scores.json`：`meta.schemaVersion` 為 `1.1`（laya judge，`judge = {model, revision,
  calibrated}`）或 `1.2`（LLM 評審團，`judge = {kind: "llm-jury", members, calibrated}`）。
  兩者以 `schemaVersion` 為 discriminated union 的 tag。
- `evidence jsonl`：v1.2 的列帶 `juryVotes`（或 `judge` 以 `llm-jury@` 開頭），
  其 `votes.<面向>.label/prob` **允許同為 null**（2/4 平手，視同資料不足）；
  v1.1 的列沒有 `juryVotes`，`votes` 的 `label/prob` 必填（laya 版本）。
  每行沒有版本欄位，故 :func:`arena.validate.validate_evidence_lines` 以
  「有沒有 `juryVotes`（或 jury judge）」挑模型。

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

v1.2（2026-09-30）相對 v1.1 的變化（C8，契約見實作裁定第 12 條）：

- evidence 新增 ``juryVotes``：每位評審對每個面向的原始票（鍵＝成員短名，值＝標籤或
  null——該成員這一則失敗），供日後收斂單一評審。``votes`` 改為多數決聚合結果，
  ``label``／``prob`` 可同為 null（2/4 平手）；``prob``＝同票比例（3/4=0.75、4/4=1.0）。
- evidence 的 ``judge`` 格式為 ``llm-jury@<membersHash 前 8 碼>``。
- ``scores.json`` 的 ``meta.schemaVersion`` 升 1.2，``meta.judge`` 改為
  ``{kind: "llm-jury", members: [...], calibrated: false}``。

兩種檔案：

- ``data/scores.json``       → :class:`ScoresDocument`
- ``data/evidence/*.jsonl``  → 每行一筆 :class:`EvidenceRecord`
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

# 資料契約版本。C4 `arena build` 目前寫入 scores.json 的版本仍是 1.1（laya judge），
# C8 的評審團版為 1.2；兩版 `arena validate` 都接受。`build` 更新為評審團後才會
# 把 `SCHEMA_VERSION` 切到 `JURY_SCHEMA_VERSION`（屬後續任務）。
SCHEMA_VERSION = 1.1
JURY_SCHEMA_VERSION = 1.2
# validate 接受的所有 scores.json 版本。
SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (SCHEMA_VERSION, JURY_SCHEMA_VERSION)

# 評審團 judge 識別：`meta.judge.kind` 與 evidence 的 `judge` 前綴。
JUDGE_KIND_LLM_JURY = "llm-jury"
# evidence 的 judge 字串格式：`llm-jury@<membersHash 前 8 碼>`。
JURY_JUDGE_PATTERN = r"^llm-jury@[0-9a-f]{8}$"

# evidence 參照格式：`<路徑>.jsonl#l<行號>`。
# 目錄前綴可省略，所以計畫範例 "evidence/2026-09-29.jsonl#l1204" 與
# 種子資料的 "evidence.sample.jsonl#l1" 都合法。
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
# v1.2 evidence 的 judge 字串（`llm-jury@<8 碼 hex>`）。
JuryJudgeRef = Annotated[str, StringConstraints(pattern=JURY_JUDGE_PATTERN)]


class _ContractModel(BaseModel):
    """所有契約模型的共同設定：拒絕未定義欄位，避免打錯字靜默通過。"""

    model_config = ConfigDict(extra="forbid")


class JudgeInfo(_ContractModel):
    """v1.1（laya）的評分器資訊。"""

    model: str = Field(min_length=1, description="評分器模型名稱，例如 laya")
    revision: str = Field(min_length=1, description="評分器版本或 commit sha")
    calibrated: bool = Field(description="是否已通過校準驗證（語意是「已通過 C5 校準」）")


class JuryJudgeInfo(_ContractModel):
    """v1.2（LLM 評審團）的評分器資訊（實作裁定第 12 條）。"""

    kind: Literal["llm-jury"] = Field(description='評分器種類，固定為 "llm-jury"')
    members: list[Annotated[str, Field(min_length=1)]] = Field(
        min_length=1, description="評審成員模型 id（排序後串接即 membersHash 的來源）"
    )
    calibrated: bool = Field(description="是否已通過校準驗證（語意是「已通過 C5 校準」）")


class DimensionSpec(_ContractModel):
    """`meta.dimensions` 的一筆：站方表格欄位的宣告（順序即欄位順序）。"""

    id: str = Field(min_length=1, description="面向 id，例如 quality")
    label: str = Field(min_length=1, description="站方顯示名稱，例如 智能")


class _MetaFields(_ContractModel):
    """``scores.json`` 兩版共用的 meta 欄位（版本／judge 由子類提供）。"""

    generatedAt: datetime = Field(description="產出時間（ISO 8601）")
    windowDays: int = Field(ge=1, description="取樣窗口天數")
    kind: Literal["community-sentiment"] = Field(
        description="資料種類，明確標示這不是 benchmark"
    )
    disclaimer: str = Field(min_length=1, description="對外顯示的免責聲明")
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


class Meta(_MetaFields):
    """``scores.json`` 的詮釋資料（v1.1，laya judge）。"""

    schemaVersion: Literal[1.1] = Field(description="資料契約版本，固定為 1.1")
    judge: JudgeInfo


class MetaV12(_MetaFields):
    """``scores.json`` 的詮釋資料（v1.2，LLM 評審團 judge）。"""

    schemaVersion: Literal[1.2] = Field(description="資料契約版本，固定為 1.2")
    judge: JuryJudgeInfo


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
    """``data/scores.json`` 的完整結構。

    ``meta`` 依 ``schemaVersion`` 分流 v1.1（laya judge）與 v1.2（llm-jury judge），
    讓舊檔在 C8 換 judge 後仍能通過 validate（實作裁定 12）。
    """

    meta: Annotated[Meta | MetaV12, Field(discriminator="schemaVersion")]
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
    """一次 pass 的六題投票結果（v1.1；laya 版，label／prob 必填）。

    鍵固定為 ``overall`` ＋五個面向 id（`VOTE_IDS`），每值 ``{label, prob}``；
    ``extra="forbid"`` 讓缺鍵／多鍵都在 validate 時被指名。
    """

    overall: OverallVote
    quality: FacetVote
    speed: FacetVote
    tokenEfficiency: FacetVote
    tokenUsage: FacetVote
    priceValue: FacetVote


class _NullableVote(_ContractModel):
    """v1.2 的單面向聚合票：``label`` 與 ``prob`` 要嘛都有值、要嘛同為 null。

    null 代表該面向 2/4 平手（視同資料不足，build 自動排除）；不允許只 null 一半。
    """

    @model_validator(mode="after")
    def _label_prob_together(self) -> "_NullableVote":
        if (self.label is None) != (self.prob is None):
            raise ValueError("label 與 prob 必須同時有值或同時為 null（2/4 平手）")
        return self


class JuryOverallVote(_NullableVote):
    """v1.2 總評的聚合票：positive／negative／neutral，或 null（平手）。"""

    label: OverallLabel | None = Field(default=None)
    prob: Probability | None = Field(default=None, description="同票比例；平手為 null")


class JuryFacetVote(_NullableVote):
    """v1.2 單一面向的聚合票：positive／negative／not-discussed，或 null（平手）。"""

    label: FacetLabel | None = Field(default=None)
    prob: Probability | None = Field(default=None, description="同票比例；平手為 null")


class AggregatedVotes(_ContractModel):
    """v1.2 的六題多數決聚合結果（鍵固定為 ``VOTE_IDS``）。"""

    overall: JuryOverallVote
    quality: JuryFacetVote
    speed: JuryFacetVote
    tokenEfficiency: JuryFacetVote
    tokenUsage: JuryFacetVote
    priceValue: JuryFacetVote


class MemberVotes(_ContractModel):
    """v1.2 的逐票原始票（evidence 的 ``juryVotes``）：每位評審對每面向的一票。

    鍵＝成員短名（member id 的 ``/`` 後段），值＝該成員的標籤或 null（該成員這一則
    呼叫失敗）。所有面向的成員鍵集合必須一致，確保逐票可完整回溯（實作裁定 12）。
    """

    overall: dict[str, OverallLabel | None]
    quality: dict[str, FacetLabel | None]
    speed: dict[str, FacetLabel | None]
    tokenEfficiency: dict[str, FacetLabel | None]
    tokenUsage: dict[str, FacetLabel | None]
    priceValue: dict[str, FacetLabel | None]

    @model_validator(mode="after")
    def _member_keys_consistent(self) -> "MemberVotes":
        key_sets: dict[frozenset[str], str] = {}
        for facet in VOTE_IDS:
            votes = getattr(self, facet)
            if not votes:
                raise ValueError(f"juryVotes.{facet} 不得為空")
            if any(not name for name in votes):
                raise ValueError(f"juryVotes.{facet} 的成員短名不得為空字串")
            key_sets.setdefault(frozenset(votes), facet)
        if len(key_sets) > 1:
            facets = "、".join(key_sets.values())
            raise ValueError(f"juryVotes 各面向的成員鍵集合必須一致（{facets}）")
        return self


class EvidenceRecord(_ContractModel):
    """``data/evidence/YYYY-MM-DD.jsonl`` 的每一行（v1.1，laya 版）。"""

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
    # 以下兩欄由 C2 落地時先寫 null，交由 `arena score` 回填；
    # 因此「結構合法但尚未評分」是合法的 evidence（plan.md 實作裁定第 7 條）。
    votes: Votes | None = Field(
        default=None, description="六題投票（overall＋五面向）；未評分為 null"
    )
    judge: str | None = Field(
        default=None, min_length=1, description="評分器與版本，例如 laya@<sha>；未評分為 null"
    )


class EvidenceRecordV12(_ContractModel):
    """``data/evidence/YYYY-MM-DD.jsonl``（v1.2，LLM 評審團版；實作裁定 12）。

    與 v1.1 的差別：``votes`` 的聚合票允許 null（平手）；新增 ``juryVotes`` 逐票；
    ``judge`` 格式為 ``llm-jury@<8 碼 hex>``。``votes`` 非 null 時
    ``juryVotes``／``judge`` 必填；``votes`` 為 null（例如某位評審呼叫失敗）
    時仍可保留部分 ``juryVotes`` 供稽核。
    """

    hash: str = Field(min_length=1, description="去重鍵（正規化內容的 hash）")
    modelId: str = Field(min_length=1, description="對應 scores.json 的 model id")
    source: str = Field(min_length=1, description="來源，例如 reddit／x／hn")
    url: str = Field(min_length=1, description="原文連結")
    author: str | None = Field(
        default=None, min_length=1, description="原作者；補不到時為 null"
    )
    postedAt: datetime = Field(description="張貼時間（ISO 8601）")
    text: str = Field(min_length=1, description="貼文內容")
    votes: AggregatedVotes | None = Field(
        default=None, description="多數決聚合票；未評分或評審失敗為 null"
    )
    juryVotes: MemberVotes | None = Field(
        default=None, description="逐位評審的原始票（鍵＝成員短名）"
    )
    judge: JuryJudgeRef | None = Field(
        default=None, description="評審團識別，格式 llm-jury@<membersHash 前 8 碼>"
    )

    @model_validator(mode="after")
    def _jury_fields_required_with_votes(self) -> "EvidenceRecordV12":
        if self.votes is not None and (
            self.juryVotes is None or self.judge is None
        ):
            raise ValueError(
                "v1.2 evidence：votes 非 null 時 juryVotes 與 judge 皆必填"
            )
        return self


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
    "JURY_SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "JUDGE_KIND_LLM_JURY",
    "JURY_JUDGE_PATTERN",
    "EVIDENCE_REF_PATTERN",
    "OVERALL_VOTE_ID",
    "FACET_DIMENSION_IDS",
    "VOTE_IDS",
    "DEFAULT_WEIGHTS",
    "EvidenceRecord",
    "EvidenceRecordV12",
    "ScoresDocument",
    "ModelEntry",
    "Meta",
    "MetaV12",
    "JudgeInfo",
    "JuryJudgeInfo",
    "DimensionSpec",
    "Votes",
    "AggregatedVotes",
    "MemberVotes",
    "OverallVote",
    "FacetVote",
    "JuryOverallVote",
    "JuryFacetVote",
    "PriceUsdPerMTok",
    "dimension_key_errors",
]
