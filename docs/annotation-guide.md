# 人工標註指南（C5 校準驗證）

> 版本：v1（2026-09-29）**已凍結**。本檔是 `laya` 評分器校準驗證（C5）的 ground truth 標註規則；
> 一旦開始標註就不可再改判準（改了要重標，否則標註集不能用）。要改請先提修訂並重跑。
> 依據：`docs/research/jev-scoring.md`「校準驗證方法」全節（R1 筆記）、
> `docs/plan.md` 資料契約 v1.1 與實作裁定第 8 條。
> 對應工作檔：`data/calibration/annotation-worksheet.jsonl`（由 `python -m arena.calibrate sample` 產生）。

---

## 0. 這個流程在做什麼

我們要驗證「JEV 評分器（`laya`）判斷社群貼文態度的準確率與**校準度**」是否達到上線門檻
（`--min-accuracy 0.80 --max-ece 0.10`）。為此需要一份**人工標註的 ground truth**：
從 evidence 池分層抽出 150 則貼文，逐則標出**六個面向**的正確態度（gold）。

- **標註者只看貼文本身，絕對不看模型預測。** 工作檔裡刻意沒有任何 `label`／`prob` 欄位
  （要對照時才用 `hash` join 回 evidence，見第 5 節）；這是防 anchoring 的設計，請不要自行
  去 evidence 檔比對預測後再標。
- 一份工作檔同時標六個面向：**每筆都要把六個 `gold_*` 全部填完**，或整筆留空（尚未標）。
  部分填寫會被 `make-evals` 擋下（避免靜默漏標）。
- 標籤只能填固定字串（英文小寫），不可自創：
  - `overall`：`positive`／`negative`／`neutral`
  - 五個面向：`positive`／`negative`／`not-discussed`

---

## 1. 六個面向的定義（照 v1.1 rubric）

下表是 `arena score` 送給評分器的題目（`src/arena/score.py` 的 `QUESTION`）與對應網站欄位。
標註時，你回答的問題與評分器**完全相同**，只是由人來回答。

| 面向 id | 網站欄位 | 評分器問的問題（原句） |
| --- | --- | --- |
| `overall` | 總評 | What is the author's **overall attitude** toward the AI model discussed in this post? |
| `quality` | 智能 | What is the author's attitude toward the model's **capability and output quality** (correctness, intelligence, reliability)? |
| `speed` | 速度 | What is the author's attitude toward the model's **response speed, latency, or throughput**? |
| `tokenEfficiency` | Token 效率 | What is the author's attitude toward **how concisely the model answers and how efficiently it uses context and tokens**? |
| `tokenUsage` | Token 用量 | What is the author's attitude toward **how many tokens (or how much of a usage quota) the model consumes** to complete tasks? |
| `priceValue` | CP 值 | What is the author's attitude toward the model's **price and value for money** (API pricing, subscription cost, or free-tier value)? |

**核心分界（最常錯）**：

- `total`（`overall`）＝對模型整體的評價；`neutral` 是它的第三個選項。
- 五個面向的第三個選項是 `not-discussed`（貼文**沒談**該面向，或**談了但沒有評價立場**），
  **不是** `neutral`。`not-discussed` 不適用於 `overall`；`neutral` 不適用於五面向。
- 「比較但未表態」（例：「A 的輸出是 $12/M，B 是 $8.80/M」）→ 該面向 `not-discussed`，
  除非作者明示哪個貴／便宜或哪個划算——那才算 positive／negative。

### 1.1 `overall`（總評）

- `positive`：讚美、推薦、表達滿意、說比替代品好、說值得花錢、期待使用。
- `negative`：批評、抱怨、說比替代品差、說要換掉／退訂／要求退款。
- `neutral`：陳述事實、問問題、比較但未表態、純發布消息、內容與模型評價無關。

**真資料範例（只展示，不給答案）**

1. `reddit`／`anthropic/claude-sonnet-5.5` —
   <https://www.reddit.com/r/singularity/comments/1wsmeu8/sonnet_55_is_second_on_artificial_analysis/>
   > Sonnet 5.5 is second on Artificial Analysis

2. `reddit`／`anthropic/claude-sonnet-5.5` —
   <https://www.reddit.com/r/Anthropic/comments/1w8puyd/bye_claude_after_15_years_and_give_me_my_money/>
   > Bye Claude after 1,5 years and give me my money back please … went from 3 x $200 accounts to
   > zero subscription accounts in a month. And now only using gpt/codex … has it not crossed your
   > mind that maybe there is a problem with the product … You are not getting money back for credits.

第 1 則是「公告型」貼文（只在報排名、沒有評價語），第 2 則是明確的不滿與退訂——正好展示
`overall` 要怎麼在「事實陳述」與「明確表態」之間取捨。

### 1.2 `quality`（智能：能力、正確性、聰明度、可靠性）

- `positive`：稱讚能力／答案品質好、正確、聰明、可靠、贏過其他模型、通過某 benchmark。
- `negative`：批評能力差、答錯、幻覺、不可靠、推理差、退步。
- `not-discussed`：沒談能力／品質；或只提到但沒有評價（例：只說「已發布」）。

**真資料範例**

1. `reddit`／`anthropic/claude-sonnet-5.5` —
   <https://www.reddit.com/r/singularity/comments/1wslxcu/claude_sonnet_55_released/>
   > It scores better than Opus in some benchmarks for agentic coding? … Switched back to Claude
   > because it is better now than astra.

2. `x`／`z-ai/glm-5.3-prime` —
   <https://x.com/SabirS/status/2104390649701158932>
   > Also noticed GLM-5.3-Prime on Alibaba that's faster version of regular GLM-5.3. But can't find
   > any coverage for it. Not smarter than just faster than GLM-5.3.

第 2 則同時是 `quality` 與 `speed` 的對照：作者說它「沒有更聰明，只是更快」——同一個句子
在 `quality` 是負面、在 `speed` 是正面。請把每一面向當成獨立的一題來答。

### 1.3 `speed`（速度：回應速度、延遲、吞吐）

- `positive`：說快、延遲低、吞吐高、比前代快、即時。
- `negative`：說慢、卡頓、要等很久、吞吐低。
- `not-discussed`：沒談速度；或只說「快」是行銷文案而沒有具體敘述。

**真資料範例**

1. `x`／`anthropic/claude-sonnet-5.5` —
   <https://x.com/red_man67/status/2104757281929797773>
   > Anthropic just made its everyday Claude model faster and cheaper. Sonnet 5.5 runs 30% faster
   > than Sonnet 5 …

2. `x`／`anthropic/claude-sonnet-5.5` —
   <https://x.com/learnaifaster/status/2104756636539875833>
   > It’s 30%+ faster than Sonnet 5, can cost up to 30% less per task, and even beats Opus 5.5 on
   > Terminal-Bench 4.0 for agentic coding.

第 2 則一句話同時談到 speed（快）、`tokenUsage`／`priceValue`（更省）、`quality`（benchmark 勝出）——
一次把四個面相標滿，是常見情形。

### 1.4 `tokenEfficiency`（Token 效率：囉嗦度、上下文／token 利用效率）

問的是**回答有多精簡、上下文用得有多有效率**（不是「完成任務總共燒多少」，那是 `tokenUsage`）。
網站欄位說明：「囉嗦與否／上下文利用率」。

- `positive`：精簡、不囉嗦、上下文利用好、KV cache 省、不需一直重貼上下文。
- `negative`：囉嗦、離題、長篇大論、過度思考（overthinking）、浪費上下文、system prompt 爆量。
- `not-discussed`：沒談精簡度或上下文效率。

**真資料範例**

1. `reddit`／`deepseek/deepseek-v3.1` —
   <https://www.reddit.com/r/LocalLLaMA/comments/1wfbnhc/hoping_for_optimized_smarter_upcoming_models_like/>
   > If they make Qwen4.0 35b moe that will be as smart as Qwen3.8 27b and doesn't overthinking
   > like 3.8 does on xhigh …

2. `reddit`／`anthropic/claude-sonnet-4` —
   <https://www.reddit.com/r/ClaudeAI/comments/1w61jq4/fable_51s_claudeai_system_prompt_is_now_138k/>
   > Fable 5.1's Claude.ai System Prompt is now 138k tokens (up from 24k in May 2025 …) …
   > that isht better be always on cache oml

---

### 1.5 `tokenUsage`（Token 用量：完成任務燒多少 token／額度消耗）

問的是**完成任務所需的 token 總量或吃到多少額度**（額度、重置、rate limit、週用量都在此）。

- `positive`：省 token、吃得少、額度耐用、用量低。
- `negative`：吃很多 token、很快把額度用完、砍額度、單位任務成本變高。
- `not-discussed`：沒談 token 用量／額度。

**真資料範例**

1. `reddit`／`openai/gpt-6-sol` —
   <https://www.reddit.com/r/codex/comments/1wo8fhw/okay_they_literally_cut_our_quota_by_half_gpt_6/>
   > Okay, they literally cut our quota by half. GPT 6 Sol got hit too. … I’m not seeing better usage
   > vs 5.6 and it’s marketed as being half the cost.

2. `x`／`anthropic/claude-sonnet-5.5` —
   <https://x.com/0xAI42exe/status/2104754740282417571>
   > Sonnet 5.5 keeps the same price as Sonnet 5 but typically uses far fewer tokens, making it up to
   > 30% cheaper per task in Anthropic’s testing.

第 2 則同時牽涉 `tokenUsage`（用更少 token）與 `priceValue`（每任務更便宜）——這是
`tokenEfficiency`／`tokenUsage`／`priceValue` 三者的典型交界，請各別判斷：描述「用量」給
`tokenUsage`，描述「單價」給 `priceValue`，描述「囉嗦／上下文」給 `tokenEfficiency`。

### 1.6 `priceValue`（CP 值：價格與性價比）

問的是**定價、訂閱費、免費額度價值**，不是額度用量（那是 `tokenUsage`）。

- `positive`：便宜、划算、CP 值高、降價、免費額度大方。
- `negative`：貴、太貴、漲價、CP 值差、不值這個錢、退訂因價格。
- `not-discussed`：沒談價格／性價比；或只客觀列出價格但沒有評價。

**真資料範例**

1. `reddit`／`x-ai/grok-4.7` —
   <https://www.reddit.com/r/cursor/comments/1wmswj9/grok_47_is_about_25_times_as_expensive_as_46/>
   > Grok 4.7 is about 2.5 times as expensive as 4.6 … I have been running the exact same task for
   > 2 days now with a Cursor Ultra plan …

2. `reddit`／`z-ai/glm-5.3-prime` —
   <https://www.reddit.com/r/AIToolsPerformance/comments/1wq46ve/qwen38_max_prime_at_12m_output_vs_glm_53_prime_at/>
   > GLM 5.3 Prime sits at $2.80/M input and $8.80/M output, Qwen3.8 Max Prime at $4.00/M in and
   > $12.00/M out … The pricing is where they split.

第 2 則只把兩家價格並列、沒有說誰划算 → 是「比較但未表態」，`priceValue` 的答案為何？
請依第 1 節的分界自己判——本指南不給答案。

---

## 2. 邊界案例與強制規則（遇到就照這裡）

### 2.1 先問「這則在講哪個模型／哪個主體？」

- 主體是**某個 AI 模型** → 正常標。
- 主體是**用模型的人、模型公司、某個人、行銷 hype**，而不是模型本身 →
  `overall` 標 `neutral`，並在 `notes` 寫 `off_target`，五面向依內容照標（多半 `not-discussed`）。

**真資料範例（off_target）**：`reddit`／`google/gemini-2.5-pro` —
<https://www.reddit.com/r/Bard/comments/1wpyn3j/people_hyping_gemini_4_pro_dont_forget_this/>
> fire this guy Logan is an embarrassment to Google deepmind, he's turned into a hyping shill with
> few actual achievements …

這則在罵「某個人 hype」，不是評價模型的智能／速度／價格 → `overall=neutral`、`notes=off_target`。
（`laya` 這類貼文容易誤判，這正是要人工標出來的原因。）

### 2.2 諷刺（sarcasm）

字面正面、語意負面 → **依語意標 negative**。

> 構造例：*"Oh great, it hallucinated again. Truly incredible engineering."* → `overall=negative`

### 2.3 混合語氣（mixed）

「大部分正、但有一句明顯負」或真的各半：

- **規則（寫死）**：以**主要語氣**為準；真的分不出主次時，`overall` 填 **`neutral`**，
  並在 `notes` 寫 **`mixed`**。C5 計算時把這筆當 `neutral` 收進來（本指南選定「算 neutral」，
  不排除）。
- 五個面向**各自獨立**判斷，不要因為整體是 mixed 就全部填 `not-discussed`。

### 2.4 否定句

照語意，不要照字面：

- *"I can't recommend it enough"* → `positive`
- *"not bad at all"* → `positive`
- *"not a fan"* → `negative`
- *"hardly the improvement over X"* → `negative`

### 2.5 歸屬錯誤（一則提到多個模型）

- 貼文主要評價的模型**不是**這一列的 `modelId` → `overall=neutral`、`notes=off_target`。
- 一則同時大力評價兩個模型、且分不清歸屬 → 也記 `off_target`（這類本來就該在 C2 收集端過濾，
  標註時如實記下即可）。

### 2.6 行銷／公告文案

官方或第三方的發布文案（「Introducing X, now with 1M context, 50% off」）：若只是規格與優惠、
沒有作者自己的評價語 → `overall=neutral`；有明確「faster」「cheaper」「best」等評價語則照語意標
（通常 `speed`／`priceValue` 會有正面）。**不確定就記在 `notes`。**

### 2.7 長文與截斷

貼文最多 1200 字元（收集端已截斷），模型 state 實際只看得到約 320 tokens。
若你覺得重點被截掉、判不下去 → 照現有文字標，並在 `notes` 寫 `truncated`。

---

## 3. 標註流程（照做就好）

1. **開檔**：`data/calibration/annotation-worksheet.jsonl`（每行一筆 JSON）。
   用任何文字編輯器逐行填，或見 README「C5 校準流程」的建議作法。
2. 每筆要填：
   - 六個 `gold_*`（`gold_overall`、`gold_quality`、`gold_speed`、`gold_tokenEfficiency`、
     `gold_tokenUsage`、`gold_priceValue`）——**六個都要填**。
   - `notes`：自由文字。常用標記：`mixed`、`off_target`、`truncated`、`ambiguous`。
     沒特別狀況就留 `null`。
   - `annotator`：你的名字／代號。
   - `annotatedAt`：標註時間（ISO 8601，例：`2026-10-01T09:30:00Z`）。
3. **只看 `text` 與 `url`**（`url` 可點開看上下文）。**不要**去查 `data/evidence/` 裡的 `votes`
   ——那是模型預測，看了會 anchoring。
4. 標完跑一次 `python -m arena.calibrate stats data/calibration/annotation-worksheet.jsonl`
   確認「完成」數＝150、「部分」＝0。
5. 產生評測集：
   ```bash
   .venv/bin/python -m arena.calibrate make-evals data/calibration/annotation-worksheet.jsonl
   ```
   預設輸出 `data/calibration/gold.jsonl`（用 `hash` join 回 evidence 取原文與來源；
   `tags` 放來源名，供 `laya-evals --slice tag`）。
6. 若之後要改標註：改 workheet 後重跑第 5 步即可（gold 檔每次整份重產）。

**常見錯誤**

- 把五面向的第三個選項填成 `neutral`（**錯**，要用 `not-discussed`）。
- 把 `overall` 填成 `not-discussed`（**錯**，overall 沒有這個選項）。
- 一行六個 gold 只填了幾個（`make-evals` 會報「只標了部分面向」）。
- 自行新增欄位（工作檔欄位固定；預測欄位是被明文禁止的）。

---

## 4. 第二人重標與 Cohen's κ（信度檢查）

單人標註由 jason 完成。行有餘力時，請**第二人獨立重標 30 筆**（同一份工作檔抽 30 筆，
**不告知第一人的答案**），算 Cohen's κ：

- **κ ≥ 0.70** 才認為指南可操作、標註集可信。
- κ < 0.70 → 代表類別定義有問題：**先改指南、重標，再進 C5**，不要硬用。
- 六個面向可**分別**算 κ（`overall` 與五面向各自一組），弱的面向優先修定義。

κ 的算法（`overall` 用 3 類、面向用 3 類都適用）：

```
po = 兩人一致的筆數 / 總筆數
pe = Σ_c (第一人標 c 的比例 × 第二人標 c 的比例)
κ  = (po − pe) / (1 − pe)
```

若環境有 scikit-learn，可直接 `cohen_kappa_score(a, b)`。Dice 一致性也可一併看，但門檻以 κ 為準。

第二人重標的 30 筆**不進** `gold.jsonl`（gold 仍以第一人為準）；κ 的結果寫進
`docs/research/jev-scoring.md` 的 C5 紀錄。

---

## 5. 為什麼工作檔沒有模型預測？（防 anchoring）

`laya` 的預測 `label`／`prob` 存在 `data/evidence/*.jsonl` 裡，**刻意不複製**進工作檔。
如果標註者先看到模型答案，會往模型答案靠，量出來的 accuracy 會虛高、ECE 也失去意義。

要對照時，用 `hash` 做 join：`make-evals` 就是以 `hash` 回 evidence 取原文與來源；
C5 報告要算「模型 vs 人工」時也一律用 `hash` join。

---

## 6. 附錄：抽樣與可重現

- 抽樣：`python -m arena.calibrate sample`（來源 × 信心帶分層；`overall` 的
  `answer_confidence < 0.70` 加權 2.5 倍；目標 n=150、每來源 ≥ 25）。
- 固定 seed `20260929`：同池重跑**位元組相同**；中繼資料（各層實抽數）寫在同名的
  `.meta.json`。
- 各面向的 ECE 分析要用**該面向自己的** `prob` 分帶（`calibrate.band_counts`），
  不是都用 overall 的。
- 標註完成後跑：
  ```bash
  LAYA_DEVICE=cpu .venv/bin/laya-evals run data/calibration/gold.jsonl \
    --model english --device cpu --batch-size 8 \
    --min-accuracy 0.80 --max-ece 0.10 --slice tag \
    --markdown docs/calibration-report.md --json docs/calibration-report.json
  ```
  （n=150 時 ECE 用 `bins=5`；離開碼 0 通過、1 未達門檻、2 用法錯誤。）

## 7. 裁決更新 v1.2（2026-09-29，owner 批准；與 §2.1/2.5/2.6 衝突處以本節為準）

第一輪四模型標註的 40 筆平手暴露了兩條界線模糊，裁決如下（強制照做，不再是「多半/如實記下」語氣）：

### R1 主體原則（強制）
貼文**主要評價的對象不是本列 `modelId`**（包括講的是清單外的新模型，如 Astra/Fable/Luna/4 Pro 傳聞等）：
- `overall = neutral`，且**五面向全部 `not-discussed`**（不是「依內容照標」——主體錯了，內容方向不屬於這列）。
- `notes = off_target`。
- 判斷步驟：先回答「這則主要在誇/罵**誰**」→ 不是本列 modelId 就走本規則，直接定案，不用再看面向。

### R2 轉述型評價（面向照內容算）
作者轉述官方公告、行銷文案、第三人稱 benchmark/排名（「快 30%」「排名第二」「半价」）：
- `overall = neutral`（作者本人沒有表態）。
- **五面向照內容的方向性陳述標**：「更快/延遲低」→ `speed=positive`；「便宜/半價/CP 高」→ `priceValue=positive`；
  「排名第二/打敗 X」→ `quality=positive`（被比較輸的一方若是本列 modelId 則 `quality=negative`）；
  空有形容詞（"revolutionary!"）但無方向性事實 → 該面向 `not-discussed`。
- 直白版：面向量測「社群提到該面向時流出的情緒」，不分轉述或原創；overall 量測「作者本人的立場」。

### 重標程序
四標註員依 v1.2 重標第一輪的 40 筆平手列（不見彼此答案、不見第一輪自己的答案）；
≥3/4 多數 → gold；仍平手 → 記 `ambiguous` 排除並如實入報告（歧義率是測量結果的一部分）。
