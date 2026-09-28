# llm-arena · C3：score（JEV 逐則評分）

- 專案：`/home/jason/workspace/agent/llm-arena`
- 要讀：`docs/plan.md`（C3、評分兩層設計）、`docs/research/jev-scoring.md`
- 前置：`llm-arena-r1-jev-research.md`、`llm-arena-c2-collect.md`

## 目標

對 C2 收集到的每一則貼文，判定它對該模型的態度（positive / negative / neutral）與**校準機率**。

## 兩層設計

1. **慢層（做一次）**：用強推理模型＋rubric 定義「品質／速度／價格 CP 值」的判斷準則與邊界案例，寫進 `config/rubric.md`
2. **快層（做很多次）**：用 R1 選定的 JEV 模型對逐則貼文分類，輸出 `label` 與 `prob`

## 一定要做

- **遮蔽模型名稱**：送評時不能讓評分器知道是哪家的模型（避免自我偏袒）
- 貼文中常見「比 Claude 強」這類相對比較——評分器要判斷「這則在談哪個模型、態度是什麼」，不是叫它自己比模型
- 結果寫回 evidence jsonl 的 `label`、`prob`、`judge` 欄位

## 驗收條件

- [ ] 對固定輸入集重跑，`label` 完全一致、`prob` 變動在容許範圍內
- [ ] `config/rubric.md` 存在且可被非作者讀懂（含邊界案例）
- [ ] 有測試驗證「遮蔽模型名」確實生效（例如同一句話換模型名，分數不變）
- [ ] 處理長貼文與多模型混雜貼文的策略有寫明

## 注意

**不要讓模型直接吐一個 7.8 分。** 這裡只出「逐則標籤＋機率」，分數由 C4 的公式算。
