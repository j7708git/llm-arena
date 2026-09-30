# laya／JEV 用法盤點與「怎麼用才能提升準確性」（C7 前置研究）

> 研究日期：2026-09-29（實際執行 2026-09-29 14:50–16:10 UTC）
> 用途：C7「laya 救援研究（elicitation vs capability）」的**文獻／生態調查**，不含 gold 實驗。
> 上游筆記：`docs/research/jev-scoring.md`（R1，2026-09-29）。**本檔不重複 R1 已查的內容**
> （pip 安裝、`answer_confidence` vs `confidence`、溫度 bucket 出廠值、`USE_TF=0`、
> 8 個 probe、A3 措辭變體、laya-evals 基本用法）；只寫在其之上挖到的新資訊。
> 實驗沙箱：`/tmp/opencode/llm-arena-c7-research/`（不入版控）。
> 本機環境：Linux、12 核 CPU、23 GiB RAM、無 NVIDIA GPU。laya `0.3.21`（R1 建好的 venv 重用）。

## TL;DR（結論與選型建議，3 句內）

1. **病灶是 domain fit，不是問法**：laya 官方 HF repo 自帶的評測表就把 `sentiment and rating`
   列為 **in-task 0.442 / zero-shot 0.362**，與我們量到的 0.4424 **幾乎逐位相同**；官方
   README 也自稱「base checkpoints 在 typed-decisions 上近亂猜，laya 是**待特化的快底座**，
   不是 zero-shot 決策引擎」。R1 那種措辭微調不可能補上 44→80 的缺口。
2. **HF 上的 12 adapters／98 finetunes 沒有對口的現成品**（唯一的情緒特化是財經新聞
   `shanaka95/laya-fintiment`，zero-shot 0.70→微調後 0.95）；真正對「短文字三類態度」對口的
   是**新出現的 open-jev 生態**（`com-kotobalabs/open-jev-deberta-v3-large`，Apache-2.0，
   官方訓練集含 SST-5 polarity，in-domain 0.854 / OOD 0.690，H100 一輪訓練 ≈ $0.26）。
3. **C7 若要留在 laya 上**，官方文件可用的結構槓桿只有三個（`noul` 改 labels、兩階段閘門、
   `choice:3-5` 溫度重擬），而官方對溫度的唯一承諾是「修 ECE，不改準確率與 argmax」；
   本研究的實機 smoke probe 顯示 `noul` 閘門在我們的資料型態上方向是錯的（見 §3.2）。

---

## 選型細節

### 1. Domain fit：官方自己的數字就否定了「是我們問法有問題」

**【官方 repo 內資料（最高證據力）】**HF `convaiinnovations/laya` 在我們 pin 的 revision
`55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`（lastModified 2026-09-24）**內含** `eval/results.md`
與 `eval/results.json`——是「指標經過校準後」的官方評測：

| task family | questions | accuracy | ECE | NLL |
| --- | --- | --- | --- | --- |
| **sentiment and rating（in-task）** | 961 | **0.442** | **0.438** | 3.545 |
| response quality scoring（in-task） | 3146 | 0.581 | 0.023 | 1.009 |
| conversation outcomes（in-task） | 3600 | 0.482 | 0.019 | 0.693 |
| topic classification（in-task） | 749 | 0.939 | 0.029 | 0.196 |
| **sentiment and rating（zero-shot）** | 600 | **0.362** | 0.291 | 1.798 |
| emotion and tone（zero-shot） | 600 | 0.583 | 0.318 | 1.976 |
| 全體 in-task | 23024 | 0.753 | 0.030 | — |
| 全體 zero-shot | 2400 | 0.651 | 0.204 | — |

（`eval/results.json` 另有 `calibration_temperature: [1.6369, 1.2514, 1.9834]`（choice/score/noul）、
`act_policy.eval_in.automation_rate = 1.0`、`accuracy_when_acting = 0.803`——後者是
`action.act_probability` 永遠 1.0 的來源，見 §3.5。）

**這張表的份量**：

- 我們的 gold 成績 `choice_accuracy 0.4424`（六題平均）與官方 **in-task sentiment 0.4422**
  在同一個數字上。不是巧合：我們的任務形狀（讀短文字→判態度）就是它的 sentiment 任務族。
- 官方對 sentiment 的 ECE 也**爛到 0.438**（我們量到 0.1342，比官方還好）。這表示
  「信心不可靠」在 sentiment 任務上是官方已知的、模型內生的問題，不是我們的校準流程有 bug。
- 同一張表裡 laya 強的任務族是 `intent and routing` 0.991、`moderation and safety` 0.967、
  `topic classification` 0.939——全是「答案就寫在字面上」的分類；sentiment/attitude 需要
  infer 作者立場，是它最弱的一族。這與 PM 的 warning（官方高分題型是結構化決策，不是讀貼文
  判態度）完全一致。

**旁證（官方 README 的另一張表，held out vs in training mix）**：

| task | laya | 註 |
| --- | --- | --- |
| AG News 4 labels | **0.947** | in training mix |
| BoolQ | **0.830** | in training mix |
| DAIR Emotion 6 labels | **0.573** | held out |
| prompt-injections | 0.698 | held out, n=116 |
| SST-5（ordinal score） | **0.372** | held out |

→ **held out 的情緒／態度類任務就是 0.37–0.57 帶**。作者自己也在部落格寫：
「部分特化的財經分類任務受益於自迴歸模型的推理深度」（`mgks.dev`，2026-09-20）。

**【社群經驗，與我們的症狀逐條對上】**（HF model-card discussions / GitHub issues）

- **issue #99**（2026-09-21）：對「真實、長、嘈雜的社群貼文」做 7 類單標分類，
  zero-shot `laya-multilingual` 貼近多數類；預測坍縮到固定兩個選項；
  **空的 state、或只有裸標籤名（無描述）→ 同一個選項、信心 0.85**；
  一個不需領域推理的二元 probe（「有沒有提到 BTC？」base rate 12%）**答對 0.37、73% 答 yes**。
  結論（原作者的說法）：「RLCD head 是在合成 agent-state 上訓練的，能泛化到那個 regime，
  但**不能**泛化到『讀一則長的真實貼文再套 rubric』」。他也回報
  **「信心 ~0.6 median，與對錯無關，所以低信心 abstain 沒用」**。
- **discussion #14**（JhouCode）：MASSIVE en 官方數字 78.33% **四位小數完全複現**，
  但拿自己的論文段落分類只剩 **25.6%**（多數類 42.4%）；TF-IDF+LR 有 70.5%。
  pollix 的回覆是規律化的版本：「**zero-shot laya 在『答案就寫在 state 的字裡、標籤又少』時強，
  標籤一多或措辭相近就掉很快**（jevbench: sst2 92% vs banking77 38%）」。
- **discussion #7**：中文語音指令三分類，Jev(雲端) 20/20、**15 行 regex 19/20**、
  **laya 10/20**。另一則 pollix 的觀察：encoder 凍結時，「把 relation 用文字講出來」才學得動。
- **issue #555 / discussion #20、#6**（`instax-dutta/sysone-bench`，sealed 1,190 cases、
  與我們同一個 weights commit `55cf4c4e`、laya 0.3.11、CPU）：9 個 suite 上
  **laya 0.6863 vs jev-1.13.0 0.9065 vs Qwen2.5-1.5B PCD 0.6048**；
  其中 **emotion 0.6562 vs 0.8438**、**sst5 0.3333 vs 0.6500**、mnli 0.5583 vs 0.8667。
  ECE（choice）三者都很低（0.0009–0.0028），gating@0.85：laya 69% coverage at 0.953、
  Jev 83% at 0.988。**但**：該 gold 是「一人看過全部、單一審閱者、無 κ、無仲裁」
  （provenance.json 明載），作者自己說不能跟 #450 比。
  後續 v4 更新：「**emotion 是三模型之牆，卡在 0.54–0.55**」。

**判讀**：對「態度／情緒」這一族，把判準從 laya 換成「更貴的 JEV」會到 0.84
（同批資料、同題目），但**沒有任何 zero-shot 決策模型在這族上過 0.9**。
門檻 0.80 對這個任務族在 zero-shot 下是不現實的；要嘛換任務設計（見 §5／§C7 清單），
要嘛特化（見 §2）。

### 2. 特化 checkpoint 盤點（HF 實查 2026-09-29）

HF API 實查（`/api/models?filter=base_model:finetune:convaiinnovations/laya`）：
**98 個 finetunes**（R1 記的 94 已過時）、**12 個 adapters**（全部是
`GoatHerder/Ariadne-Laya-*`：TD/Support/FinanceTopics/Spam/Injection/BioEvidence/Moderation/
PrivacyFlags/Evidence/BankingIntent/Contracts + Thanabordee/AudioLaya-poc），
另有一批量化／ONNX／MLX／CoreML 移植（`mys/laya-GGUF`、`FluidInference/laya-coreml` 等）。

**逐類看下來，沒有任何「社群貼文態度」對口的**：

| 找到的 | 是什麼 | 對我們有用嗎 |
| --- | --- | --- |
| `shanaka95/laya-fintiment` | **3 類財經情緒**（positive/negative/neutral）。zero-shot 0.7024 → 微調後 **0.9486**（15,355 筆 held-out，F1 0.94–0.95） | 標籤形狀對，**領域不對**（FinGPT 新聞/推文，字面極化）。但它是「同一顆底座微調就能修好」的**成本標竿** |
| `Ariadne-Laya-*`（12 adapters） | 客服/垃圾信/注入/合約/銀行意圖 | 全部不是情緒 |
| `gtm-k/laya-product-decision-assist` | 4 類 **supports/contradicts/mixed/insufficient**；base 28.1% → 微調 50.0%（64 個合成 case，亂猜 25%） | 有 `insufficient` 類的**唯一現成範例**（我們的 `not-discussed` 最近親）；但樣本太小、只有 64 case，且**選項順序敏感**（四種順序全同答案 40/64、全對 22/64） |
| `InfinimindCreations/laya-news-decisions` | 新聞 4 題（10 類 topic + score + noul） | 不是情緒；但附了 `laya-rlcd-training` |
| 其他 90 餘個 | 遊戲、瀏覽器 agent、語言在地化、ONNX/量化 | 無關 |

**成本／可行性（官方 + 社群實測）**

| 路線 | 資料需求 | 硬體 | 實測時間/成本 | 來源 |
| --- | --- | --- | --- | --- |
| 官方 notebook（RLCD） | **teacher 機率分布**（不是硬標籤），範例 1,200 cases / 6,000 decisions | Kaggle 免費 2×T4 | demo 4–6 min；**~30k questions × 4 epochs ≈ 4–5 h** | [finetune.md](https://github.com/NandhaKishorM/laya/blob/main/docs/finetune.md)（實查） |
| `laya-fintiment`（第三方復刻同一條路） | 61,017 筆 train + 400 校準 | **1× 12 GB GPU** | 4 epochs / 7,624 steps / effective batch 32 | 其 model card（實查） |
| **CPU 微調（可行！）** | 128 筆合成案例（單一 noul + 單一 choice） | **12 核 CPU** | **~14 分鐘 / 8 epochs** | GitHub **PR #705**（open，2026-09-29）+ PR #704 的 `research/scripts/finetune_single_device.py`。**尚未合併進 main**（今日 `raw/main` 對兩者皆 404） |
| `stuntd`（Apache-2.0，`pip install "stuntd[train]"`） | 「幾千筆你自己的流量」；凍結 encoder、只訓 head、encoder 輸出快取一次 | 筆電 GPU 即可（pollix：快取後「幾分鐘」） | 官方自稱 banking77 risk 30.0% → 72.5%；shell gate 45% → 97% | [bladedevoff/stuntd](https://github.com/bladedevoff/stuntd)（實查） |
| `laya-rlcd-training`（第三方開源訓練迴圈） | 你的資料一欄一題（`{"id","text","topic","severity","violent"}`），AG News 為例：4,000 train / 400 gold | 需 GPU 較實在 | README 沒給數字 | [HF `InfinimindCreations/laya-rlcd-training`](https://huggingface.co/InfinimindCreations/laya-rlcd-training)（實查） |

**兩個關鍵的規模／效果對照**（決定 C7 值不值得走這條路）：

- **資料量決定一切**：256 筆合成 case → 28.1%→50.0%（gtm-k）；61k 筆 → 0.7024→0.9486
  （fintiment）。我們可用的標註只有 gold ~150 筆（且要 held-out 切 100/50）——
  **遠低於會有效果的量級**，除非用 teacher 蒸餾產生大量弱標籤。
- **head-only 微調不是萬能**：discussion #14 的 JhouCode 拿 4k 長段落重訓 laya 的決策 head，
  只到 40.8%（多數類 42.4%），而**同一個 encoder 的 mean-pool + logistic regression 有 68.5%**。
  即：任務若不吃 laya head 的 inductive bias，換讀出方式比微調 head 更有效。

**新發現：open-jev 生態（R1 完全未涵蓋）**——HF 上「JEV 形狀」的開源模型已成一族：

| 模型 | 底座 | 授權 | 對我們的意義 |
| --- | --- | --- | --- |
| **`com-kotobalabs/open-jev-deberta-v3-large`**（69 likes、2675 dl） | DeBERTa-v3-large，512 ctx（state 切到 256） | Apache-2.0 | **最對口**：訓練集是 banking77 + **SetFit/sst5（5 級 sentiment + 3 類 polarity choice + noul）** + boolq；in-domain **0.854** / OOD **0.690**，ECE 0.022/0.035；**只用公開 gold、不需要 teacher**；18,000 states / 42,000 questions、1 epoch、**單張 H100 229 秒 ≈ $0.25**；訓練用 gold-preserving augmentation（選項打亂、改寫模板、distractor 抽換、**noul 否定並翻 gold**）p=0.7。程式與 ADR：[kotoba-lang/typed-decisions](https://github.com/kotoba-lang/typed-decisions) |
| `leobitz/jev-berta-base-zeroshot-classifier` | DeBERTa-v3-base，MIT | MIT | 更小的 zero-shot 版，Jev 形狀 API |
| `ZefanCai/Open-Jev-2B/9B/27B` | Qwen3.5 + LoRA + decision head | Apache-2.0 | 需 GPU server；2B 版 temperature 1.5188（512 筆校準） |
| `Meanblock/JEV-CPU`（48 likes） | Qwen3-0.6B，MIT | MIT | 純 CPU、~1s/決策；SemIf 的 CPU 移植 |
| `akhilaaa3/Jev-Omni`（309 likes）、`autotrust/JEV-27B` 等 | — | — | 生態規模的旁證 |

`typed-decisions` 那份 repo 還公開了一個**負面結果**（對我們選型有用）：
ModernBERT-large + 「新 marker token hidden state 打分」的 head **完全學不動**（banking77
intent ≈ 0.12）；改成「option text token 的**平均** × question 平均」的 span head 才學得動
（DeBERTa-v3-large 0.787、RoBERTa-large 0.710、ModernBERT-base 0.539，但 ModernBERT-large
仍停 0.39）。layа 用的正是 ModernBERT-large。這解釋了為什麼 laya 對「文字語意」的利用偏弱。

### 3. 官方 elicitation／用法規則（只列 R1 沒有的）

#### 3.1 題目結構與選項設計

- **官方 presets 用 `other: "none of the above"` 當 catch-all**（`laya/presets.py::email_questions`）。
  這是官方唯一像「not-discussed」的東西——但語意是「其他類別」，不是「沒談」。
- **`noul` 的 labels 可在 0.3.21 覆寫**（`docs`→`## Decision Primitives`）：
  `{"labels": {"false": "NOT_MENTIONED", "true": "MENTIONED"}}`。官方同時警告
  「標籤敏感度因 checkpoint 與 state 而異，不要把 `A`/`B` 當萬用解」。
- **官方對「讀社群貼文判態度」這種兩階段閘門（step 1：有沒有談；step 2：談了就問態度）
 沒有任何文件**。我到今天為止在官方 README（77 KB GitHub 版）、docs 站全部頁面、
  190 個 open issues、22 個 HF discussions 裡**查不到**「unanswerable／not discussed／
  irrelevant 選項」的指引。→ **明確說：查不到，這是空白，不是我們漏看。**
- **選項順序／措辭的敏感度，官方只有「別用 boolean 標籤」（#156/#377）與**
  `research/eval/metamorphic.py` 的變體工具**；有人在 issue #635 提議把
  「選項重排＋改名後答案是否改變」做成品質訊號（`soft_stability`），顯示官方也承認這問題存在。
  issue #706 進一步指出這類比較在 token budget 緊時會被預算混淆（`budget_confounded`）。

#### 3.2 `noul` 與二元閘門（C7 假設 2 的核心）

【官方文件證實】`noul` 永遠是 `[false, true]` 兩個 slot，**預設渲染給模型看的就是
`false:` / `true:`**（`render_options()` 實查原始碼）→ 會出現 label prior 主導（#156：
不管 state 都答 negative）。官方建議的 workaround 有兩個：
(a) 0.3.21 的 `labels` 覆寫；(b) 「把它改成**兩選項 `choice`**、鍵用中性字、把 yes/no 寫進
描述」（README Honest limits 原文給了範例）。

【本機實測 smoke（4 則貼文，非實驗，只驗 API 行為）】用 arena 的 `speed` 題做三種變體：

| 貼文 | 3 選項（arena 現行） | 2 選項（complains/does_not_complain） | `noul`＋labels 覆寫（NOT_MENTIONED/MENTIONED） |
| --- | --- | --- | --- |
| 沒談速度（付費/介面） | positive **0.468**（nd 0.397） | does_not_complain 0.682 | **0.183** |
| 沒談速度（敷衍） | positive **0.487**（nd 0.358） | does_not_complain 0.908 | **0.181** |
| 明確談速度快 | positive 0.901 | does_not_complain 0.798 | 0.477 |
| **明確談速度慢** | negative 0.933 | complains 0.842 | **0.320** ← 反向錯 |

→ `noul` 閘門在我們的型態上**方向是錯的**（明確抱怨慢的貼文只給 0.32「有提到」），
不是調門檻能救的。2 選項版則把「沒抱怨」與「沒談」混為一談，資訊量反而更少。
**兩階段閘門要成立，第一步必須自己有 held-out 準確率 ≥ 現行 3 選項的 not-discussed 判準**，
而 smoke 顯示現成 `noul` 不具備。

#### 3.3 Router 的分流邏輯

【官方文件證實】`Router` 只做 **script/語言偵測**（<0.5 ms 純 Python），在
`laya`（English, ModernBERT-large, 512 ctx）與 `laya-multilingual`（mmBERT-base, 1024 ctx）之間選；
**`laya-typed-decisions` 不會被自動選到**，要 `model="typed-decisions"` 明講。
`Router(preload=True)` 首次載入 CPU 上 193–464 ms，之後 <1 ms。
【社群經驗】獨立評測的 v3 跑出：**西/法/德文仍留在英語 checkpoint**（Router 看的是 script），
只有 590 次呼叫中的 15 次走 multilingual；換句話說**拉丁字母的非英文會靜默地送進英語模型**。
我們若持續排除非英文貼文，這條不影響；但要記得 `--model english` 不會幫我們擋掉英文以外。

#### 3.4 長文截斷與 `predict_long`（C7 假設 4 的核心）

四件事，全部實查：

1. **state 預算的官方說法低估了。** README 寫 `max_len - head_max_len` ≈ 320 tokens；
   issue #696（PR 待合併）指出 `head_max_len` 是**上限**、實際 head 只用到需要為止。
   【本機實測，用 `src/arena/score.py` 的**原文** QUESTION 逐題量】
   `overall` head 86、`quality` 103、`speed` 94、`tokenEfficiency` 106、
   `tokenUsage` **109**、`priceValue` 99 → **實際 state 預算 402–425 tokens**
   （binding = tokenUsage 的 402）。**R1 的「~320 tokens」比實際少了約 20%**，
   而 C2 端已截到 1200 字元（英文約 250–300 tokens）→ 依目前規則**多數貼文不會被 laya 截斷**。
2. **截斷方向由 state 的型別決定**（`agent.py:764` 實查原始碼）：
   `truncate_left = isinstance(state, list)`。**dict / str → 保留開頭**；
   **list（對話串）→ 保留結尾**。我們現在傳 `{"post": text}`（dict）→ 長文**尾端被丟掉**。
   （駭法：傳 `[text]` 可保留尾部，但那是給對話串設計的語意，非文件承諾。）
3. **`predict_long` 不是長文的正解**（官方原文）：`choice`/`score` 取「**最有信心的那個窗**」、
   `noul` 取最大值窗，並明載「回傳的是決定性窗的機率，**不是整份文件的校準機率**」；
   且「`noul` 的 max 會隨窗數上升而漂高，即使沒有訊號」。→ 只用於**定位**，不能當 C5 的機率。
4. **位置效應比長度效應更大**（issue #697，研究 PR）：固定長度、把請求在文件裡掃過去，
   20 題的準確率從 0.40 到 0.95 都有；多數類是 0.45。→ 貼文把重點放前或放後會改變答案。

#### 3.5 `min_confidence`（0.3.21 新增，我們裝的版本就有）

【本機實測】`Router.predict(..., min_confidence=0.99)` → 每個 answer 多一個
`low_confidence: True/False`，原始 label/機率保留。簽名實查：
`predict(state, questions, model=None, task=None, lang=None, lang_guess=None, hooks=None,
on_predict_start=None, on_predict_end=None, hooks_raise=None, hooks_timeout=None,
max_len=None, head_max_len=None, min_confidence=None)`。
官方也提供 **per-request 放寬預算**：`predict(state, questions, head_max_len=512, max_len=1024)`。

【官方＋社群對 gating 的警告】

- 官方 `docs/staged-adoption.md`：「門檻是**應用端政策**，要在代表性 held-out 資料上擬合，
  沒有可跨 checkpoint／題型／語言／風險通用的數字」；`confidence` 只提供排序，不代表正確。
- issue **#394**：門檻**不隨選項數轉移**；README 舊版寫死 `conf >= 0.85`，
  在 20 選項時選出的子集比整體還差。來源是 HF discussion #2（`choice:11+` 溫度 0.1006）。
- issue **#635**：MASSIVE en 300 題裡 65 個錯答案有 **37 個 `answer_confidence ≥ 0.90`**；
  並給出 AUROC：**手寫 held-out 280 題上 `answer_confidence` 的 AUROC 只有 0.647**
  （MASSIVE 20 選項 0.831、6 選項 0.913）。→ 對我們這種「自由文本、標籤少」的集合，
  信心的排序力接近丟硬幣，與我們量到的「倒掛」一致。
- issue #99 原始回報：「信心 ~0.6 median 與對錯無關，abstain 沒用」。

**結論（推論）**：`min_confidence` 是一個**可用但對我們無效**的閘門。要在 C7 用它，
前提是信心單調性檢查通過；以目前 gold 的倒掛與 #635 的 AUROC，**不預期會過**。

### 4. 校準與溫度重擬

【官方文件證實】

- 重新擬合「每個（題型, 選項數）一個溫度」可把 mean ECE 從 **0.466 → 0.081**（english）；
  載入時數值被 clamp 到 **[0.5, 5.0]**，無效值 fallback 1.0，原始值保留在
  `agent.temperature_raw` / `agent.temperature_by_options_raw`（**本機實測**：`choice:11+`
  0.10058… → 留在 `_raw`，生效值 0.5）。
- **bucket 值優先於 per-type 值**。官方 notebook 匯出時會**刪掉繼承來的
  `temperature_by_options`**，否則舊 bucket 會靜默蓋掉新擬合的 `temperature`。
- **【新坑】notebook 的擬合範圍與 runtime clamp 不一致**（issue #637、PR #642 open）：
  `fit_one_temp()` clamp `[0.1, 10]`，但 runtime clamp `[0.5, 5.0]`。
  有人實測擬合出 **9.886 → 上線只有 5.0**（另一輪 7.10 → 5.0）。
  → **我們自己擬合 `choice:3-5` 時，值必須守在 `[0.5, 5.0]`，並驗證 reload 後生效值相同**；
  `shanaka95/laya-fintiment` 的 choice 溫度就是 **5.013**（貼在邊界上）。
- 官方唯一承諾：溫度縮放**不改變 argmax／準確率**，只動信心。
  → **對 accuracy 0.4424 的病灶完全無效**；它能修的只有 ECE。
- `laya-evals` 進階（`docs/evals.md` 實查）：`--slice` 可**重複**；
  `compare report.json --baseline base.json --tolerance choice_accuracy=0.02`；
  `--revision SHA` / `--revision english=SHA`（**多 checkpoint 各一個 repo，一個 SHA 不可能全中**）；
  `--onnx`；`--batch-size` 會**同時抬高 latency 與降低 cost_per_decision**；
  report 帶 `config.timing`、`revisions`。

【社群經驗】第三方校準層：`Second Thought`（discussion #13）在 `laya-typed-decisions`
24 筆客服決策上量到 **accuracy 87.5% 但 ECE 0.62**——再次說明「答對」與「信心可信」是兩件事。
另 `rbrus/laya-as-judge`（Apache-2.0，7★）雖是現成的 judge 封裝，但【實查】其
**PyTorch backend 是未完成的 scaffold（只吐均勻分布）、真正的推論要走 MLX/Apple Silicon**，
在我們的 Linux CPU 機器上**不可用**。

### 5. 替代方案成本對比（更新 R1）

#### 5.1 成本論證在我們的規模上失效

R1 選 laya 的理由之一是「自架、零 token 成本」。用 OpenRouter 現價（`/api/v1/models`，
實查 2026-09-29）算一遍**同一個任務**（每則貼文 6 題、一次呼叫，state ~400 tokens、
rubric ~350 tokens、輸出 ~120 tokens JSON）：

| 選項 | 單價（in/out，per M） | 單則成本 | 216 則一趟 | 3 家多數決 |
| --- | --- | --- | --- | --- |
| `google/gemini-2.5-flash-lite` | $0.10 / $0.40 | $0.000123 | $0.027 | $0.080 |
| `xiaomi/mimo-v2.6-flash` | $0.14 / $0.28 | $0.000139 | $0.030 | $0.090 |
| `qwen/qwen3.8-flash` | $0.15 / $0.47 | $0.000169 | $0.037 | $0.110 |
| `z-ai/glm-5.3-flash:batch` | $0.06 / $0.20 | $0.000069 | $0.015 | $0.045 |
| `google/gemini-3.5-flash-lite` | $0.30 / $2.50 | $0.000525 | $0.113 | $0.340 |
| **laya（自架）** | $0 | $0 | $0 | $0，但 **0.4424** |

→ **一整個月（2,000 則）用 3 家 flash 多數決 ≈ $1**。也就是說「省錢」不再是選 laya 的理由；
judge 選擇應該純粹看**準確率／校準／可稽核性**。**這是本節最重要的更新。**

#### 5.2 文獻：cascade 的價值被「相關錯誤」抵銷

- `arXiv:2609.26550` **JEV-as-a-Judge: Accept When Confident, Escalate When Unsure**（CMU,
  2026-09-22）：JEV 在一般偏好與「有證據支撐的事實性」上與最強 LLM judge 差 3 個百分點以內，
  成本只要 **0.36%**；但**在無參考文本的自由寫作上，「所有受測 judge 都不可用」**
  （三個 judge 都近亂猜卻很自信，mean max prob 0.91–0.96，JEV error-detection AUROC 0.498）。
  → 我們的任務正是「無參考文本的態度判斷」，這篇論文本身就在警告這個 regime。
- `arXiv:2609.29769` **JEV vs. LLMs as Rubric Judges**（Rao & Callison-Burch, 2026-09-24）：
  JEV 與三個 flash-tier LLM judge 在 27 個配對比較中只有 8 個顯著不同（JEV 在二元判準超前、
  只在 graded 判準落後）；LLM judge 成本是 **29–325 倍**、時間 **30–220 倍**；
  **但 cascade 幾乎沒用**：LLM judge 重複了 JEV 幾乎所有「最自信的錯誤」，
  重播錄下來的判決最多只能比最佳單一 judge 多 **1.5 分**（oracle 門檻也只有 2.0）。
  → 對我們的意義：若把 laya 當第一關、LLM 當第二關，**要先驗證兩者的錯誤不相關**；
  以我們「not-discussed → 硬給 positive」這種系統性錯誤，很可能是相關的。
- `arXiv:2609.24052`（交通事故敘述 → 機率化變數）與 `REFLEX with Jev`
  （`arXiv:2609.26532`：τ=0.5、95% 成功率、平均 1.12 次強模型呼叫 vs 純強模型 88%/4.10 次）
  屬「結構化欄位抽取」regime，與我們的社群態度任務不同族。

#### 5.3 其他替代（R1 已比過，這裡只補新資訊）

- **AgentJev**：R1 結論不變（權重定位矛盾、需自架 server）。
- **LLM2Jev**：R1 結論不變（是框架、要自備 4B 級 base、無 GPU 不現實）。
- **託管 JEV**：上面 §1 的獨立評測已把差距量出來了（emotion +0.19、sst5 +0.32、mnli +0.31，
  全部 Holm 校正後顯著）。若真要走這條，要注意它**封閉權重、違反本專案可重跑／可回溯的要求**。
- **純規則偵測 `not-discussed`**（R1 沒討論）：沒有任何現成套件。但兩條旁證支持值得一試：
  (a) discussion #7 的 15 行 regex 在該任務上贏 laya；
  (b) issue #99 顯示 laya 在最簡單的「有沒有提到 X」二元 probe 上只 0.37、且有 73% yes bias。
  做法：每個面向一組關鍵詞／片語表（fast/slow/latency/price/$/per million/quota/tokens…），
  命中→才送模型判態度；不命中→`not-discussed`。**成本 0、可稽核、可版本控管**。
  【推論】以我們 gold 的分布（約 9 成面向是 not-discussed），這條規則的**天花板很高**
  （見下方 C7 清單的第 0 項）。

---

## 最小可用範例（可直接參考的程式/指令）

### 0. 重現本研究用到的實查指令

```bash
# 官方評測表（我們 pin 的 revision 內就有）
curl -sL https://huggingface.co/convaiinnovations/laya/raw/main/eval/results.md
# 列出所有 laya finetune / adapter
curl -s "https://huggingface.co/api/models?filter=base_model:finetune:convaiinnovations/laya&limit=200" \
  | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))'
# 官方文件的完整版（HF model card 只是子集）
curl -sL https://raw.githubusercontent.com/NandhaKishorM/laya/main/README.md | less
```

### 1. 量出「我們的 schema 到底吃多少 state 預算」（實測過，402 tokens）

```python
import os; os.environ["USE_TF"]="0"; os.environ["LAYA_DEVICE"]="cpu"
import laya
from laya.common import build_sequence
agent = laya.load("convaiinnovations/laya", device="cpu")
mx, hmx = agent.cfg["max_len"], agent.cfg["head_max_len"]      # 512 / 192
q = {"t":"choice","ins":"<您的 instructions>","crit":{"positive":"…","negative":"…","not-discussed":"…"}}
ids, markers, stats = build_sequence(agent.tok, {"post": ""}, q, max_len=100000, head_max_len=hmx, return_stats=True)
head = len(ids) - 1
print("head", head, "state_room", mx - head - 1, stats)
```

### 2. `min_confidence`（0.3.21 就有，實測過）

```python
res = agent.predict(state, questions, min_confidence=0.85)
ans = res["answers"]["speed"]
if ans.get("low_confidence"):      # answer_confidence < 0.85
    escalate(ans["choice"])
```

### 3. `noul` 的 labels 覆寫（0.3.21 新 API，實測過）

```python
{"discussed": {"type": "noul",
               "instructions": "Does this post explicitly discuss how fast or slow the model responds?",
               "criteria": {"false": "the post says nothing about response speed or latency",
                            "true": "the post talks about response speed or latency"},
               "labels": {"false": "NOT_MENTIONED", "true": "MENTIONED"}}}
# 回傳鍵仍是 "noul"，值仍是 P(true)
```

### 4. 溫度重擬＋注入（值必須在 [0.5, 5.0]）

```python
agent = laya.load("convaiinnovations/laya")
agent.temperature_by_options["choice:3-5"] = T   # T ∈ [0.5, 5.0]，擬合後立刻生效
# 驗證：reload 後 print(agent.temperature_by_options["choice:3-5"]) 仍等於 T
```

### 4b. 取得可信的 checkpoint sha（0.3.21 實測有）

```python
agent = laya.load("convaiinnovations/laya")
print(agent.revision)                       # 55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851
from laya.revisions import PINNED_REVISIONS # 三個 checkpoint 的已審核 sha
print(PINNED_REVISIONS)
```

### 5. 若要走特化：open-jev 的訓練成本是可以複製的

```bash
# kotoba-lang/typed-decisions：公開 gold、無 teacher，H100 一輪 ≈ $0.26
# 注意：最後一行需要 Modal 帳號（或自己把 modal_app.py 的訓練搬到本地/其他租用 GPU）
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -e ".[test]"
.venv/bin/python -m typed_decisions.data --out data     # banking77 + sst5 + boolq
modal run modal_app.py::encoder --model microsoft/deberta-v3-large --lr 5e-5 --epochs 1
```

---

## 已知坑與注意事項（本檔新增，R1 的 12 條不重複）

1. **`eval/results.md` 就在 HF repo 裡，選型前先看它。** 我們（和 R1）在 C5 之前都沒看，
   白跑了一整輪 44% 的驚嚇。sentiment/attitude 是它公開承認的弱項。
2. **README 有兩份**：HF model card（23 KB）與 GitHub `README.md`（77 KB）。
   「Automated Confidence Gating」「Calibration」「Fine-Tuning」「Long documents:
   `predict_long`」只在 GitHub 版。`docs/staged-adoption.md` 連到的錨點也只存在 GitHub 版。
3. **state 預算 = `max_len - 實際 head - 1`，不是 `max_len - head_max_len`**；
   我們的 schema 實測 402–425 tokens（R1 的 320 是低估）。
4. **截斷方向看 state 型別**：`{"post": …}`（dict）保頭丟尾；`[… turns]`（list）保尾。
   長貼文的結論若在尾端，會被靜默丟掉。
5. **`noul` 的 `false:`/`true:` 標籤 prior**（#156）**在 0.3.21 有 `labels` 可覆寫，但實測仍不可靠**：
   明確「很慢」的貼文只給 0.32 的 MENTIONED。
6. **`min_confidence` 的 AUROC 在自由文本上只有 0.647**（官方 issue #635 的實測）；
   高信心錯誤很多（37/65 錯在 ≥0.90）。gate 之前先量單調性。
7. **溫度擬合範圍 vs runtime clamp 不一致**（#637）：notebook clamp `[0.1,10]`、
   runtime clamp `[0.5,5.0]`，擬合 9.886 上線變 5.0。自己控在 `[0.5,5.0]`。
8. **bucket 溫度優先於 per-type 溫度**；官方 notebook 匯出時刪掉 `temperature_by_options`
   就是為了這個。我們若沿用出廠 bucket 值，任何 per-type 擬合都會被蓋掉。
9. **`predict_long` 的機率不是文件級校準機率**（官方原文），`noul` 的 max 還會隨窗數漂高。
10. **位置效應 > 長度效應**（#697）：同一份文件把請求掃過位置，20 題準確率 0.40–0.95。
11. **`action.act_probability` 永遠 1.0 的機制**（#185）：decision head 是 pre-norm 且殘差未歸一化，
    離開 head 的 activation 約為 encoder 的 300 倍，把 act head 飽和；
    `scorer` 不受影響（自己有 LayerNorm），所以選項機率是好的。**永遠不要拿它當 gate**。
12. **獨立 benchmark 的 gold 不是無菌的**（#555）：單一審閱者、無 κ、無仲裁，
    作者自己在報告裡標 `"independent_human_review": false`。引用它的數字要一起引這個限制。
13. **`laya-as-judge` 在 Linux CPU 上跑不動**：PyTorch backend 只吐均勻分布，實作要 MLX。
14. **`laya-multilingual` 出廠完全沒有擬合溫度**（`temperature [1,1,1]`、空的
    `temperature_by_options`），官方明載；issue #99 實測信心 median ~0.6 與對錯無關。
15. **PR #705／#704（CPU 微調）尚未合併 main**（今日 raw 404）；要用得從 PR 抓。
16. **checkpoint revision 現在抓得到了（0.3.21 已修）**：issue #555 在 0.3.11 上回報
    `Agent` 不暴露 commit sha；**本機實測 0.3.21 有 `agent.revision`**
    ＝ `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`（與我們 pin 的相同），
    且 `laya.revisions.PINNED_REVISIONS` 公開三個 checkpoint 的已審核 sha
    （english `55cf4c4e`／multilingual `e4e9ddf2`／typed-decisions `1a793eb5`）。
    → C3 的 `judge` 欄位可以直接寫 `f"laya@{agent.revision}"`，不要再手抄 sha。

---

## 【推論】C7 該跑的實驗清單（對齊任務卡四個假設）

> 前提：gold 定案。方法紀律照 C7 卡（held-out 100/50、固定 rubric baseline、
> 每個實驗報 accuracy／ECE／信心單調性）。laya-evals CPU 110 筆 ~35 分鐘 → 先跑 50 筆。

### 第 0 項（**新增，最高優先，因為它決定前面所有數字怎麼讀**）

**算出無模型 baseline，並要求 judge 必須顯著超過它。**

- 五個面向：全部猜 `not-discussed`。
  【推論】依 progress-status「gold 約 9 成面向是 not-discussed」，這個常數預測的
  面向準確率約 **0.90**——**比 laya 的 0.4424 高一倍**，也高於 C5 的 0.80 門檻。
  `overall` 另算多數類基線。
- 產出：per-qid 的 majority-class accuracy、macro-F1、以及「laya vs 常數 baseline」的
  McNemar 檢定。**若 laya 贏不過常數 baseline，acc-based 門檻 0.80 本身就是誤導性指標**，
  應改成 macro-F1 或 per-qid gate（這是一條要回報給 owner 的設計變更）。
- 同時輸出**純規則 not-discussed 偵測器**（每面向一組關鍵詞）在同一份 gold 上的成績，
  當作「零成本替代方案」的天花板。這是 §5.3 的實證版。

### 假設 1（Domain fit／特化 checkpoint）

1. **複核官方數字**：把 `eval/results.md` 的 sentiment/attitude 數字與我們 gold 的
   混淆矩陣並列，寫成「官方已知弱項，我們複現」的一段；確認 0.4424 不是 bug。
2. **決定性實驗**：拿 `com-kotobalabs/open-jev-deberta-v3-large` 在**同一份 held-out 50**
   上跑同一組 6 題（它的 API 是 `options` 而非 `criteria`，需要一層轉接）。
   它訓練集含 SST-5 polarity，是唯一有理由期待的現成品。
   - 過線 → 換 judge（要一起評：Apache-2.0、512 ctx、CPU fp32 可跑、ECE 0.022 是官方自報）。
   - 不過線 → 這族任務的 zero-shot 上限就在 0.55–0.65，直接進「特化 or 換任務設計」二選一。
3. **特化可行性**：只在 §5 的 smoke 顯示「值得」時才做。要有：
   (a) 資料從哪來（我們的 ~150 筆 gold 遠不夠；要么 teacher 蒸餾，要么放棄）；
   (b) 平台（官方 notebook 的 **Kaggle 免費 2×T4** 是最實際的路；CPU 微調要先抓 PR #704/#705）；
   (c) 成本（官方 ~30k questions × 4 epochs ≈ 4–5 h 2×T4；open-jev 的 42k questions ≈ $0.25 H100）。
   **不要**拿 gold 當訓練資料然後在同一個 gold 上報成績。

### 假設 2（任務結構：A3 只改措辭，沒動結構）

四個變體，全部在 held-out 50 上、對照組固定為「現行 rubric（A3 版）」：

1. **兩階段**：`choice` 閘門（鍵用中性字，例 `mentioned`/`not_mentioned`，**不要用 noul**——
   §3.2 的 smoke 顯示 noul 方向是錯的）→ 只在 `mentioned` 時問態度。
   報「閘門本身的 accuracy」＋「通過閘門後的條件準確率」。**若閘門 accuracy < 常數 baseline
   （第 0 項），此法直接淘汰**。
2. **選項集縮減**：只問 positive/negative（去掉 not-discussed），把「兩者機率都低／接近」當 gate。
   （smoke 顯示這會把「沒談」與「沒抱怨」混在一起，但要用數字證明。）
3. **`not-discussed` 換詞**：`no opinion expressed` / `irrelevant` / 把 `not-discussed` 移到
   選項順序第一或第三（`render_options` 是照 dict 插入序渲染的）。三種各跑一次。
4. **輸入表徵**：`{"post": text}` vs `[text]`（觸發左截斷、保留尾部）vs 只給 title。
   §3.4 的實測說 dict 保頭，長貼文尾端會被丟——這一項會直接把差異量出來。
5. **重驗**：六題同 pass vs 逐題單獨呼叫（A3 已驗過，重驗一次，因為 0.3.21 有
   `_reuse_question_tokens` 的改動）。

### 假設 3（信心倒掛根源）

1. **分辨「溫度 bucket 錯」vs「`answer_confidence` 在 3 選項偏態分布下失去意義」**：
   - 在 held-out 50（或另切一份純校準集，**不要**用要報成績的那 50）掃
     `choice:3-5 ∈ [0.5, 5.0]`，對每個 T 報 ECE **與 AUROC(confidence vs correct)**。
   - 若 ECE 修好了但 AUROC 不動 → 倒掛不是溫度問題，`min_confidence`／gating **永久不可用**，
     要回報 owner「gating 這條路關閉」。
   - 若 AUROC 也動 → 才值得往下做 gating 政策。
2. **對照 #635 的 AUROC 0.647**（手寫 held-out 280）與 #394 的「門檻不隨選項數轉移」：
   把我們的 AUROC 放進去比較，判斷是不是同一個病。
3. **`min_confidence` 實測**：用擬合後的 T，在 50 筆上跑 `min_confidence=0.85`，
   報 coverage vs accuracy-on-covered（不是只報 accuracy）。

### 假設 4（輸入表徵）

併入假設 2 的第 4 項，並加做：**長度切片**（`--slice tag=long`）＋「不同位置的同一則貼文」
（issue #697 的做法：把貼文放到 state 前／中／後），量位置效應。

### 判決後的產出

- **可救** → 給 C3 的完整配方（judge/checkpoint、題目 schema、溫度值、是否 gating）。
  注意：若第 0 項顯示常數 baseline ≈ 0.90，那「可救」的定義要重寫成
  「顯著優於常數 baseline 且 macro-F1 可接受」，不是單看 0.80。
- **不可救** → 附「換 judge」成本對比（§5 的表已經可以直接用），
  並明確區分兩條路：**(a) 換 zeroshot judge**（LLM 3 家多數決 ≈ $1/月，
  或 open-jev 若測得過）；**(b) 改任務設計**（面向維度改成「只報有討論的」＋用規則偵測
  not-discussed 當閘門，把模型只用在「談了之後的正負面」上——那時 P+N 的樣本數會很小，
  要在 `meta.notes` 標「僅供參考」）。

---

## 來源（連結 + 查詢日期）

| 來源 | 連結 | 查詢日期 |
| --- | --- | --- |
| **laya 官方評測表 `eval/results.md`／`results.json`（pin revision `55cf4c4e` 內）** | https://huggingface.co/convaiinnovations/laya/blob/main/eval/results.md | 2026-09-29 |
| laya GitHub README（77 KB：Automated Confidence Gating、Calibration、Decision Primitives、predict_long、English tasks、Fine-Tuning） | https://github.com/NandhaKishorM/laya/blob/main/README.md | 2026-09-29 |
| laya HF model card（23 KB，較短） | https://huggingface.co/convaiinnovations/laya | 2026-09-29 |
| laya 官方 docs：evals / staged-adoption / structured / finetune | https://nandhakishorm.github.io/laya/ 、`docs/*.md` in repo | 2026-09-29 |
| `laya/presets.py`（`other: none of the above`） | https://github.com/NandhaKishorM/laya/blob/main/laya/presets.py | 2026-09-29 |
| issue #185（act_probability 飽和機制、AUROC 0.30） | https://github.com/NandhaKishorM/laya/issues/185 | 2026-09-29 |
| issue #156（noul label prior）／#377（否定）；`labels` 覆寫在 Decision Primitives | https://github.com/NandhaKishorM/laya/issues/156 、/377 | 2026-09-29 |
| issue #361／PR #456（`min_confidence` 設計、用 `answer_confidence`） | https://github.com/NandhaKishorM/laya/issues/361 | 2026-09-29 |
| issue #394（門檻不隨選項數轉移；來源 HF discussion #2） | https://github.com/NandhaKishorM/laya/issues/394 | 2026-09-29 |
| issue #635（37/65 高信心錯；AUROC 0.647/0.831/0.913；soft_stability 提議） | https://github.com/NandhaKishorM/laya/issues/635 | 2026-09-29 |
| issue #637＋PR #642（notebook 溫度 clamp 與 runtime 不一致） | https://github.com/NandhaKishorM/laya/issues/637 | 2026-09-29 |
| issue #696（state 預算是 `max_len - 實際 head`）／#697（位置敏感度）／#706（budget_confounded） | https://github.com/NandhaKishorM/laya/issues/696 、/697、/706 | 2026-09-29 |
| issue #99（長、嘈雜社群貼文近亂猜；信心與對錯無關）／#171（presentation sensitivity） | https://github.com/NandhaKishorM/laya/issues/99 、/171 | 2026-09-29 |
| issue #555（獨立 9-suite 評測：laya 0.686 vs Jev 0.907 vs Qwen2.5-1.5B PCD 0.605） | https://github.com/NandhaKishorM/laya/issues/555 | 2026-09-29 |
| PR #704／#705（CPU 單機微調，12 核 14 分鐘；未合併 main） | https://github.com/NandhaKishorM/laya/pull/705 | 2026-09-29 |
| HF discussions #2 #3 #6 #7 #9 #13 #14 #15 #20 #21（社群實測與反饋） | https://huggingface.co/convaiinnovations/laya/discussions | 2026-09-29 |
| `shanaka95/laya-fintiment`（3 類財經情緒 0.7024→0.9486；訓練成本） | https://huggingface.co/shanaka95/laya-fintiment | 2026-09-29 |
| `gtm-k/laya-product-decision-assist`（insufficient 類；選項順序敏感；choice temp 1.409） | https://huggingface.co/gtm-k/laya-product-decision-assist | 2026-09-29 |
| `InfinimindCreations/laya-rlcd-training`（第三方訓練迴圈） | https://huggingface.co/InfinimindCreations/laya-rlcd-training | 2026-09-29 |
| `com-kotobalabs/open-jev-deberta-v3-large` + `kotoba-lang/typed-decisions`（訓練成本、span head、OOD） | https://huggingface.co/com-kotobalabs/open-jev-deberta-v3-large 、https://github.com/kotoba-lang/typed-decisions | 2026-09-29 |
| `leobitz/jev-berta-base-zeroshot-classifier`／`ZefanCai/Open-Jev-2B`／`Meanblock/JEV-CPU`（open-jev 生態） | https://huggingface.co/models?search=jev | 2026-09-29 |
| `bladedevoff/stuntd`（凍結 encoder 訓 head，Jev/OpenAI 相容 proxy） | https://github.com/bladedevoff/stuntd | 2026-09-29 |
| `rbrus/laya-as-judge`（PyTorch backend 未完成，需 MLX） | https://github.com/rbrus/laya-as-judge | 2026-09-29 |
| arXiv 2609.26550 JEV-as-a-Judge（cascade、無參考文本不可用） | https://arxiv.org/abs/2609.26550 | 2026-09-29 |
| arXiv 2609.29769 JEV vs. LLMs as Rubric Judges（相關錯誤抵銷 cascade） | https://arxiv.org/abs/2609.29769 | 2026-09-29 |
| arXiv 2609.26532 REFLEX with Jev（τ=0.5、1.12 次強模型呼叫） | https://arxiv.org/abs/2609.26532 | 2026-09-29 |
| OpenRouter `/api/v1/models`（各家 flash 現價，實 curl） | https://openrouter.ai/api/v1/models | 2026-09-29 |
| PyPI `laya`（0.3.21，2026-09-27 上架） | https://pypi.org/project/laya/ | 2026-09-29 |
| 作者自述（財經分類受益於自迴歸模型的推理深度） | https://mgks.dev/rollups/2026-09-20-why-i-built-laya-open-source-system-1-for-real-production-speed | 2026-09-29 |
| 本機實機沙箱（probe 腳本與原始輸出，不入版控） | `/tmp/opencode/llm-arena-c7-research/`（`probe_api.py`／`probe_budget2.py`／`probe_gate.py`／`probe_struct.py`） | 2026-09-29 |
| `laya.revisions.PINNED_REVISIONS` 與 `Agent.revision`（實機印出） | 本機 `laya==0.3.21` | 2026-09-29 |
