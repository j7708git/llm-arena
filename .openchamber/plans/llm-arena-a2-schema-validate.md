# llm-arena · A2：schema 定義、validate 與種子資料

- 專案：`/home/jason/workspace/agent/llm-arena`
- 要讀：`docs/plan.md`（**資料契約 schema v1**，以此為準）、`docs/plan-overview.md`
- 階段：A（可立即動工，無前置）
- **重要性：這是 `jason-lab` 的相依，完成後網站端才能動工**

## 目標

把 `docs/plan.md` 的 schema v1 變成程式可驗證的定義，並產出一份可以讓網站開發用的種子資料。

## 要做的事

1. 用 pydantic（或 JSON Schema）定義 `scores.json` 與 evidence jsonl 的格式
2. 實作 `arena validate`：檢查檔案是否符合 schema
3. 寫一份**手動的種子資料**：
   - `data/scores.json`：3～5 個模型，欄位全部填齊（含 `dimensions`、`sampleSize`、`confidence`、`evidence`）
   - `data/evidence/sample.jsonl`：幾筆範例貼文
   - 在 `meta.notes` 標明這是種子假資料

## 驗收條件

- [ ] `arena validate data/scores.json` 對合法檔回傳 0
- [ ] 對刻意改壞的檔（缺欄位、型別錯）回傳非 0，並指出**是哪個欄位**
- [ ] 種子 `data/scores.json` 通過 validate
- [ ] 種子資料欄位齊全，足以讓 `jason-lab` 開發排行榜頁（含排序與篩選所需欄位）

## 下游

`jason-lab-b2-arena-page.md`（網站端靠這份種子資料開工）
