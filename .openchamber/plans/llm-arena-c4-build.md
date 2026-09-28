# llm-arena · C4：build（聚合成 scores.json）

- 專案：`/home/jason/workspace/agent/llm-arena`
- 要讀：`docs/plan.md`（**資料契約 schema v1**、C4）
- 前置：`llm-arena-c1-fetch-models.md`、`llm-arena-c3-score.md`、`llm-arena-a2-schema-validate.md`

## 目標

把 evidence、標籤機率、模型清單聚合成網站要讀的 `data/scores.json`。

## 要做的事

- 分數由**公式計算**：正面提及比例 × 樣本數加權（權重與公式定案後寫進 `config/weights.yaml`，並在 `docs/` 說明）
- 三個維度：`quality` / `speed` / `price`，另給 `score`（總分）
- 填入 `sampleSize`、`positiveRate`、`confidence`、`mentionsBySource`、`evidence` 引用位置
- `meta` 要含 `generatedAt`、`windowDays`、`kind: community-sentiment`、`disclaimer`、`judge`
- 產出後自動跑 `arena validate`

## 驗收條件

- [ ] 產出的 `scores.json` 通過 `arena validate`
- [ ] 抽樣 20 筆，能從 `score` 連回對應的原始貼文（拿起 `evidence` 裡的位置即可找到）
- [ ] 同一份輸入重跑，輸出雜湊相同（`generatedAt` 除外）
- [ ] 樣本數過小的模型有明確處理（隱藏或標示低信心），不能讓 3 則貼文推出一個高分
- [ ] `meta.disclaimer` 明確寫出「社群聲量代理指標，非 benchmark」

## 下游

`jason-lab-b2-arena-page.md`
