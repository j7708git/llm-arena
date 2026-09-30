# llm-arena · C8：LLM 評審團 judge（取代 laya）

- 專案子目錄：本 repo（worktree）
- 要先讀：`docs/plan.md`（**實作裁定第 12 條 = 本任務的完整契約**、C8 任務節、
  evidence/scores schema 節）、`docs/research/laya-usage-accuracy.md` §5（成本依據）、
  `src/arena/score.py`、`src/arena/schema.py`、`tests/`
- 前置：無（不需 gold 定案；gold 驗證是後續任務）

## 目標

`arena score` 的 judge 從 laya（本地模型）改成 OpenRouter 四人 LLM 評審團：

1. `deepseek/deepseek-v4.1-flash:batch`
2. `z-ai/glm-5.3-flash:batch`
3. `openai/gpt-6-luna:batch`
4. `qwen/qwen3.7-flash`（owner 指定觀察員；無 batch 版，原價）

四位評審**獨立呼叫**（同一 prompt、同一 rubric、JSON 輸出、溫度 0），不得互看。
prompt 內容沿用現行 score 的六題 rubric（overall＋5 面向，標籤集同 plan.md schema 節）。

## 聚合規則（裁定 12）

- 每面向取多數；`votes.<facet>.prob` = 同票比例（3/4=0.75、4/4=1.0）
- **2/4 平手 → 該面向 `label` 與 `prob` 記 `null`**（build 自動排除）
- `juryVotes.<facet>.<member短名>` 逐票保留（短名 = member id 的 `/` 後段）
- `judge` 欄位 = `llm-jury@<membersHash 前 8 碼>`（membersHash = members 排序串接 sha256）
- `meta.judge` 改為 `{kind: "llm-jury", members: [...], calibrated: false}`，
  schemaVersion 升 **1.2**（`extra=forbid`；validate 對 1.1 舊檔仍要通過——分版本處理）

## 工程要求

- OpenRouter `chat/completions`；`OPENROUTER_API_KEY` 從環境變數讀，
  **缺 key 時明確報錯，不得靜默降級或假造 votes**
- 429/逾時：指數退避重試 ≤3 次，仍失敗 → 該筆 evidence 的 votes 記 null 並於 stderr 統計
- batch 變體走 OpenRouter batch API（非同步）；CLI 保留 `--no-batch` 走同步原價版
- 冪等：同一輸入重跑 votes 完全一致（溫度 0＋固定 prompt）

## 驗收條件

- [ ] `pytest -q` 全綠（新舊 schema 測試都在；API 一律 mock，**測試不得打真網路**）
- [ ] `arena validate` 對舊 1.1 evidence（`data/evidence/2026-09-29.jsonl`）與新 1.2 樣本都過
- [ ] 對 `data/samples/evidence.sample.jsonl` 真跑四人團：votes/juryVotes/judge 正確回填，
      平手面如實 null（**需要 key；若本機無 `OPENROUTER_API_KEY`，此項標記 PENDING KEY 並寫進回報**）
- [ ] 缺 key 時 `arena score` 以非零 exit + 清楚訊息失敗
- [ ] 更新 `docs/progress-status.md` 管線表格的 score 列

## 禁區

- 不要動 `data/calibration/`（gold 重標進行中）、不要刪 laya 程式碼（git 歷史保留即可，
  import 路徑與測試允許保留但標 deprecated）
- 不要重跑 `arena build` 覆寫 `data/scores.json`（等真跑評審團後另一步驟處理）
