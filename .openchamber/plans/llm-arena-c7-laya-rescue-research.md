# llm-arena · C7：laya 救援研究（elicitation vs capability）

- 專案：`/home/jason/workspace/agent/llm-arena`
- 要讀：`docs/progress-status.md`（交接單）、`docs/research/jev-scoring.md`（含 A3 已試過的措辭變體）、
  `docs/annotation-guide.md` v1.2、`data/calibration/`（gold 定案狀態）
- 階段：研究（決定 judge 去留）
- 動工前提：**gold 150 定案**（v1.2 重標合併完成）後才有評測基準

## 背景（owner 假設）

laya 在 C5 考卷上 44%（門檻 80）、信心與正確率倒掛。但 laya/JEV 是「即時決策」專用模型，
官方 benchmark 號稱 GPT-5.6 Sol 級——owner 懷疑是**問法（elicitation）**問題而非能力問題。
PM 警告：官方高分的题型是結構化決策（JevBench），不是讀社群貼文判態度；domain fit 要先查。

## 要調查的假設（按性價比排序）

1. **Domain fit**：laya 訓練分佈到底吃什麼任務？HF repo 的 12 adapters／94 finetunes 裡
   有沒 sentiment/text-classification 特化版（官方 README 提過 fine-tuning notebook）？
   找到一個對口的 checkpoint/adapter 比任何 prompt 工程都可能有效。
2. **任務結構**（A3 只改過措辭，沒動過結構）：
   - 兩階段：先 noul/boolean「有沒有談 speed？」談了才問態度——laya 對二元題是否靠譜？
   - 選項集縮減：只問 positive vs negative 二選＋用「無方向內容自然會亂猜」的機率当 gate？
   - 每面向獨立呼叫 vs 六題同 pass（結果理應相同，A3 已驗同 pass＝單題；重驗一次）
   - `not-discussed` 換詞：`no opinion expressed`／`irrelevant`／放在選項順序不同位置
3. **信心倒掛根源**：倒掛是 temperature bucket 錯、還是 `answer_confidence` 在 3 選項偏態
   分布下失去意義？用 gold 重擬 `choice:3-5` 溫度看能不能同時修 ECE 與排序性（R1 §步驟4）。
4. **輸入表徵**：title-only 短貼文 vs 有 summary 的貼文，laya 的 not-discussed 率差多少？
   （x／短 HN 列 accuracy 最差，可能是「資訊不足時它仍被訓練成要給決定」的 System One 特性）

## 方法紀律

- **held-out**：gold 定案後先切 100 標 50 測（或對半交叉），不要用同一份邊調邊報最終成績。
- 每個實驗都報 accuracy／ECE／信心單調性三個數，格式對齊 C5 報告（calibration-report.md）。
- 對照組固定：現行 rubric（A3 版）＝ baseline。
- laya-evals CPU 慢（110 筆 ~35 分鐘）；實驗設計先用抽樣 50 筆快跑，有希望再全量。

## 產出

`docs/research/laya-rescue.md`：
1. 每個假設的實跑結果表（指令＋輸出，不可憑記憶）
2. 最終判決：可救（給 C3 的完整新配方：checkpoint/題目結構/溫度值）或不可救（證據链）
3. 若不可救 → 附「換 judge」的成本對比建議（評審團方案當時被擱置，重新評估用）

## 驗收條件

- [ ] 至少跑過假設 1、2（結構）與 3（溫度）三組實驗，各附實際輸出
- [ ] 判決有數字支撐，不是「感覺不行」
- [ ] 若找到過線配方：在 held-out 50 筆上 accuracy≥0.80、ECE≤0.10、信心單調，
      才算「可救」；全量 gold 再複驗一次才算定案
