# llm-arena · C1：fetch-models

- 專案：`/home/jason/workspace/agent/llm-arena`
- 要讀：`docs/plan.md`（C1）、`docs/research/openrouter-api.md`
- 前置：`llm-arena-r2-openrouter-api.md`、`llm-arena-a1-cli-skeleton.md`

## 目標

合併「人工維護的模型清單」與「OpenRouter 的定價／context 資料」，產出 pipeline 用的模型清單。

## 要做的事

- `config/models.yaml`：人工維護清單（只追值得追的模型，不要全收）
- 打 `https://openrouter.ai/api/v1/models`，取定價與 context length
- 以模型 id 為鍵合併；OpenRouter 沒有的模型仍要保留（欄位留空並標記）
- 結果落地成中間檔（供 C4 使用）

## 驗收條件

- [ ] 連續執行兩次結果一致（可重現）
- [ ] OpenRouter 掛掉時，人工清單部分仍完整輸出，且明確標示哪些欄位缺漏
- [ ] 有測試覆蓋「人工清單有、API 沒有」與「API 有、人工清單沒有」兩種情況
- [ ] 不用爬 HTML，一律走 API

## 注意

人工清單是**主**，OpenRouter 是**附掛欄位**。不要反過來讓 API 決定要追蹤哪些模型。
