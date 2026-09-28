# llm-arena · R2：OpenRouter 模型清單 API 研究

- 專案：`/home/jason/workspace/agent/llm-arena`
- 要讀：`docs/plan.md`（schema v1 的 `models[]` 欄位）、`docs/plan-overview.md`
- 階段：研究（C1 的前置）

## 目標

確認 `data/scores.json` 裡哪些欄位可以從 OpenRouter 自動取得、哪些必須人工維護。

## 要調查

- `https://openrouter.ai/api/v1/models` 的完整回應格式
- 模型 id 的格式（例如 `anthropic/claude-sonnet-4`）
- 定價欄位怎麼對應到 schema 的 `dimensions.priceUsdPerMTok.{in,out}`（單位是每 token 還是每百萬 token）
- `name`、`provider` 怎麼取得
- 需不需要 API key、有無 rate limit、更新頻率
- 有沒有其他可用的公開端點（例如模型排行榜類資料）

## 產出

`docs/research/openrouter-api.md`，包含：

1. 欄位對照表：schema 欄位 ← OpenRouter 欄位（沒有對應的標「人手維護」）
2. 一次實際 curl 的精簡輸出範例
3. 呼叫建議（含快取／失敗處理）

## 驗收條件

- [ ] 有實際 curl 過的紀錄，欄位名稱與實際回應一致（不可憑記憶）
- [ ] 明確列出「無法從 API 取得、必須人工維護」的欄位清單

## 下游

`llm-arena-c1-fetch-models.md`
