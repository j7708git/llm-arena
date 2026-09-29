# llm-arena · A3：schema v1.1 多維度改造（score 六題 + votes + 種子重建）

- 專案：`/home/jason/workspace/agent/llm-arena`
- 要讀：`docs/plan.md`（**「資料契約（schema v1.1）」全節＋實作裁定 1~10**，以此為準）、
  `docs/research/jev-scoring.md`（laya 用法、QUESTION 格式、坑；其 votes 欄位映射已被 v1.1
  取代，一律以 plan.md 為準）、`src/arena/score.py`、`src/arena/schema.py`
- 階段：A3（2026-09-29 新增；**C4/C5 的前置**，完成前 C4 不開工）

## 目標

把「單一 attitude 分類」升級為「一次 pass 問 6 題的多維度投票」，並讓 schema、種子資料、
既有 evidence 全部落到 v1.1。

## 要做的事

1. **`schema.py`（v1.1）**：
   - `EvidenceRecord`：刪 `label/prob`，改 `votes: dict | None`＋`judge: str | None`。
     votes 若有值，鍵必須含 `overall`＋5 個面向 id（`quality/speed/tokenEfficiency/
     tokenUsage/priceValue`，模組常數）；每值 `{label, prob}`；overall 的 label ∈
     `positive|negative|neutral`，面向的 ∈ `positive|negative|not-discussed`（裁定 8）。
   - `ScoresDocument`：`meta.schemaVersion` = `1.1`（Literal）；新增 `meta.dimensions`
     （`[{id,label}]`）、`meta.weights`（面向 id→0~1）、`meta.sourcesCovered`；
     `models[].dimensions` 改開放 map（值 0~100 或 null），**鍵必須是 meta.dimensions
     宣告的 id**（交叉檢查，裁定 9）；`priceUsdPerMTok` 移到 model 層級（可 null）；
     新增 `dimensionSamples`（id→int）。
2. **`score.py` 六題化**：QUESTION 同一次 `predict` 傳 6 個 choice 題（每題 3 選項→仍落
   `choice:3-5` bucket）。題面（rubric 初稿，可微修但要在報告貼出最終文字）：
   - overall：沿用 R1 筆記的 attitude 題。
   - quality：對模型**能力與輸出品質**（正確性、聰明度、可靠性）的態度。
   - speed：對**回應速度／延遲/吞吐**的態度。
   - tokenEfficiency：對**囉嗦度與上下文/token 利用效率**的態度。
   - tokenUsage：對**完成任務所需 token 量／額度消耗**的態度。
   - priceValue：對**價格與性價比**（定價、訂閱、免費额度 CP 值）的態度。
   - 每題 criteria 都要明寫 `not-discussed`＝「貼文未談或談了但無評價立場」；
     題目一律**不出現模型名**（state 只有貼文，同 R1）。
   - 回填 `votes[qid] = {label, prob=answer_confidence}`；冪等条件改為 `votes 非 null 跳過`；
     `judge` 同 `laya@55cf4c4`。固定 batch_size=8。
3. **資料重建**：
   - 種子 `data/scores.json`：依 v1.1 重寫（4 模型、meta.dimensions/weights/sourcesCovered
     照 plan 範例）；`dimensions` 故意示範至少一個 null 維度（站方要能測「資料不足」渲染）；
     `meta.judge.calibrated=false`；`notes` 標【種子假資料】。
   - `data/evidence/sample.jsonl`：轉成新 shape（votes 全部 null 即可，種子不需評）。
   - 真跑 `arena score --force` 重評 `data/evidence/2026-09-29.jsonl`（24 筆，laya 已快取；
     約 1 秒/則），產出六題 votes。
4. **測試**：`test_validate`/`test_score` 改到 v1.1（未評分合法、面向與 overall 的 label
   詞彙分開驗證、dimensions 鍵交叉檢查、votes 六鍵完整、fake predictor 回 6 題答案）；
   重現性與原子寫入測試保留。

## 驗收條件

- [ ] `arena validate data/scores.json data/evidence/*.jsonl` 全回 0
- [ ] 真跑重評後的 `2026-09-29.jsonl`：24 筆都有六鍵 votes，prob ∈ 0~1，且抽 3 筆
      把 label 直覺對照原文说得通（把對照表貼進回報）
- [ ] 同檔重跑第二次不覆寫（冪等）；`--force` 重評結果逐字一致（重現性）
- [ ] pytest 全綠（既有 ~104 條中屬於 v1 欄位的要改掉，不算破壞）
- [ ] README 開發段更新（score 六題、votes 語意）

## 邊界

- 不可碰：`build.py`（C4 的）、`collect.py`/`enrich.py`（改寫 evidence 欄位時**只動
  schema/score 側**；`collect.py` 寫入的 record 構造若因 label/prob→votes 而掛，
  允許你在 collect 做**最小欄位對齊**，並在報告註明）、`cli.py`、`docs/`、`pyproject.toml`。
- commit 明確路徑、嚴禁 `git add -A`；繁中 message；不 push。
