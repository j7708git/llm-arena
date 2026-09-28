# llm-arena · R1：JEV 家族研究與校準驗證方法

- 專案：`/home/jason/workspace/agent/llm-arena`
- 要讀：`docs/plan.md`（schema v1、任務 C3/C5）、`docs/plan-overview.md`
- 階段：研究（C3／C5 的前置）

## 目標

決定評分要用的 JEV 家族模型，並定義「怎麼驗證它準不準」的流程。

## 要調查的對象

| 對象 | 位置 |
| --- | --- |
| `convaiinnovations/laya` | Hugging Face（Apache-2.0, text-classification） |
| `AgentJev-0.6B` | `github.com/malevrigns/agent-jev` |
| `LLM2Jev` | `github.com/Yinsongxu/LLM2Jev` |
| `typesafe/jev-router` | OpenRouter（**對照組，預期不適合量產評分**） |

每個都要回答：安裝方式、推論 API、輸入輸出格式、授權、能否本地跑、單則推論成本、**是否輸出校準機率**。

## 產出

`docs/research/jev-scoring.md`，包含：

1. 選型比較表與最終選擇（附理由）
2. 一個**實際跑過**的最小範例：對 5 則假貼文做態度分類（positive/negative/neutral）
3. 校準驗證方法：人工標註流程、準確率與校準曲線怎麼算、樣本數要多少

## 驗收條件

- [ ] 明確選定一個模型，並寫出「為什麼不是其他兩個」
- [ ] 附上實際執行指令與輸出（不可只貼官方 README）
- [ ] 校準驗證步驟寫到 C5 可以照著做，不必再查

## 下游

`llm-arena-c3-score.md`、`llm-arena-c5-calibration.md`
