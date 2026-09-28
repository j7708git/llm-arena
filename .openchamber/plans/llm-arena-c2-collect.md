# llm-arena · C2：collect（社群貼文收集）

- 專案：`/home/jason/workspace/agent/llm-arena`
- 要讀：`docs/plan.md`（C2、evidence jsonl 格式）、`docs/research/last30days-skill.md`
- 前置：`llm-arena-r3-last30days.md`、`llm-arena-a1-cli-skeleton.md`

## 目標

用 `last30days` 技能抓近 30 天的社群討論，落地成可回溯的 evidence jsonl。

## 要做的事

- 對 C1 清單中的每個模型（含別名／俗稱）搜尋社群討論
- 輸出 `data/evidence/YYYY-MM-DD.jsonl`，每行符合 schema：
  `hash / modelId / source / url / author / postedAt / text`（`label`、`prob` 由 C3 補）
- **去重**：以正規化後的內容 hash 為鍵（轉貼、改標題轉貼都要能抓到）
- 設定檔控制查詢來源與關鍵字

## 驗收條件

- [ ] 同一則爆紅貼文被轉貼多次，只留一筆（要有測試，用兩則近似文本驗證）
- [ ] 每筆都能用 `url` 連回原文
- [ ] 抓取失敗（來源掛掉）不會讓整批中斷
- [ ] 抽樣 10 筆人工檢視，確認確實是「對某模型的評價」而非誤命中

## 注意

不要在此階段判斷正負面——那是 C3 的工作。這裡只負責「忠實地把原文留下來」。
