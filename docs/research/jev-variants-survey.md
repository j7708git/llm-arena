# JEV-style 決策模型變體普查（C7 前置／替代品評估）

> 研究日期：**2026-09-30**（HF API、模型卡、GitHub、arXiv、OpenRouter 全部於當日實查；網站頁面皆註明其自身 `last updated`）。
> 用途：owner 指定——JEV 爆紅後市場出現大量類似變體，全面普查並逐一評估有沒有比現行路線更值得換的替代品。
> 上游筆記：`docs/research/jev-scoring.md`（R1）、`docs/research/laya-usage-accuracy.md`（R4）。
> **本檔不重複 R1／R4 已查的內容**（laya／AgentJev／LLM2Jev／typesafe-jev-router 四者對比、laya 官方 eval
> 表、laya 98 finetunes 盤點、`com-kotobalabs/open-jev-deberta-v3-large` 的訓練細節、LLM 三家 flash
> 成本表）；只寫在其之上挖到的新變體與新證據。
> 本機環境（判斷可否跑）：Linux、12 核 CPU、23 GiB RAM、無 NVIDIA GPU。
> 未做任何 gold 評測、未下載任何 > 1 GB 權重（僅以 API／model card／eval 表判斷）。

## TL;DR（結論與選型建議，3 句內）

1. **沒有「已證實」勝過 `com-kotobalabs/open-jev-deberta-v3-large` 的變體**——市場上 60+ 個 open-weight
   JEV-style 專案，**沒有一個在自己的 model card 上對「社群貼文態度」這一族報出可比的 in-domain 數字**；
   生態的公開比較表（fast-decisions、typed-decisions、JevBench）全是「營運決策／意圖／NLI」任務。
2. **但有 3 個變體值得進 C7 實測清單（判決 A）**，理由是「結構對口 + 小 + 單 pass + CPU + 有概率輸出」各有
   現成 baseline 沒有的特點：`fastino/GLiNER2.5-Decide`（340M，呼叫時才給標籤與描述，自帶 review-sentiment
   head）、`manjunathshiva/opendecider-nano`（~400M，訓練集含 GoEmotions／CivilComments，宣稱贏 laya）、
   `heman10x/rlcd-modernbert-151m`（151M，**內建 `__insufficient_evidence__` 棄答槽**，直接對應我們的
   `not-discussed`）。**hosted Jev（OpenRouter `typesafe/jev-1.13`，$0.042/M input）**列為準確率天花板對照。
3. **最重要的判讀來自 arXiv 2609.24574（2026-09-23，決策模型在計算社會科學 18 個標註任務上的評測）**：
   決策模型在 15 個任務的中位數輸給最強 LLM **11.6 macro-F1**，只在便宜的 cascade「低信心→LLM」時打平；
   且**在「peer-support 對話中的 empathy」這類主觀構念上，模型近亂猜卻報高信心**——與我們 laya 的病灶
   同族。**結論：這些變體是「值得花一次 held-out 50 去驗」的挑戰者，不是「換掉就解決」的答案**。

## 選型細節（版本、理由、替代方案對比）

### 0. 範圍界定：什麼算「JEV-style 變體」，什麼不算

符合越多越對口：(a) < 2B；(b) 不解碼文字、直接輸出**選項機率分布**；(c) 有 state ＋ typed
questions（`choice`/`score`/`noul`）介面；(d) 主打 routing/eval/classification。

**排除**（不符合或與我們無關，僅記錄以免重複查）：LLM2Jev／`anyjev`／`open-alternative-jev`／`jevify`／
`SemIf` 是**讀出框架或訓練法**（不附對口權重，要自備 base LLM，R1 已判不適用）；純 router（`typesafe/jev-router`、
s1lv3rj1nx `openjev-router-*`）；embedding（`HIT-TMG/JevEmbed-*`）；多模態／視覺（`Jev-Omni`、
`NeoHorse-Jev-4B`、`gu8anxuyu/visual-jev-4b`、`laya-vision-smolvlm-256m`）；非英文（`cainai/OpenJev-Qwen3.5-0.8b`
繁中／zh、`iapp/OpenThai-SystemOne`、`argos1111/modernbert-ja-310m-jev`、`fukayatti0/jev-japanese-judgment`、
`wwydmanski/bielik-minitron-jev` 波蘭語）；≥ 2B 解碼器（Mapika `decider-2b/4b/35b`、`kev-4b/9b/27b`、
`JevK5`(Qwen3.5-4B)、Decision-1.0 `Sol/Nox/Lux`、`this-that-model-1.0/1.2`(1.88B)、`ZefanCai/Open-Jev-2B/9B/27B`）
——本機 23 GiB RAM 無 GPU，且 R1 已排除 4B 級。

### 1. 變體清單表（實查 2026-09-30）

> 大小＝ HF API `?blobs=true` 加總權重檔；fit 評級＝對「短英文社群貼文 × 三類態度＋not-discussed × CPU × 需校準機率」的貼合度。
> **A＝值得進 C7 實測；B＝備選（條件式）；C＝不可行／不建議。**

| # | 名稱 | 來源（查詢日 2026-09-30） | 大小 / params | 任務域 | 機率輸出 | CPU | 成熟度 | fit |
|---|---|---|---|---|---|---|---|---|
| 0a | **`com-kotobalabs/open-jev-deberta-v3-large`**（現行候選） | [HF](https://huggingface.co/com-kotobalabs/open-jev-deberta-v3-large) | 1.75 GB / 434M | banking77+**sst5 polarity**+boolq | ✅ 分布 | ✅ | 69 likes / 2,675 dl | **基準 A** |
| 0b | **LLM 三家 flash 多數決**（現行候選） | 見 R4 §5.1 | 雲端 | 通用 | ✅（自報） | n/a | 成熟 | **基準 A** |
| 1 | **`fastino/GLiNER2.5-Decide`** | [HF](https://huggingface.co/fastino/GLiNER2.5-Decide)、[GitHub](https://github.com/fastino-ai/GLiNER2)、[bench 資料集](https://huggingface.co/datasets/fastino/fast-decisions) | 1.95 GB / 340M | 17 類營運決策（含 **review sentiment** 3 類） | ✅ label + confidence；**全分布未查證** | ✅ `pip install gliner2[local]` | 238 likes / 29k dl；`gliner2-base` 65 萬 dl | **A** |
| 2 | **`manjunathshiva/opendecider-nano`** | [HF](https://huggingface.co/manjunathshiva/opendecider-nano)、[GitHub](https://github.com/manjunathshiva/opendecider)、[HF blog](https://huggingface.co/blog/manjunathshiva/opendecider-beats-laya-and-jev) | 0.8 GB / ~400M（Ettin-400M） | typed-decisions；訓練含 **GoEmotions、CivilComments**、go_emotions、CLINC、DBpedia | ✅ 每選項機率 | ✅（pip `opendecider`） | 71 dl、2 likes；**新（9/27）** | **A** |
| 3 | **`heman10x/rlcd-modernbert-151m`**（Verdict OpenJev） | [HF](https://huggingface.co/heman10x/rlcd-modernbert-151m)、[GitHub](https://github.com/Heman10x-NGU/Verdict-open-jev) | 0.61 GB sf / 0.30 GB fp16-ONNX / 151M | GLiClass/ModernBERT，銀行+軟體工作流 | ✅ + **棄答槽** | ✅（ONNX/WebGPU） | 22k dl、37 likes | **A**（授權待查） |
| 4 | **`Beko2210/statim-decide-en-large`** | [HF](https://huggingface.co/Beko2210/statim-decide-en-large)、[GitHub](https://github.com/BEKO2210/statim) | 0.45 GB q8 GGUF / 0.84 GB sf / ~395M | **laya 直系微調**；typed-decisions、sentiment | ✅ | ✅（C++ 引擎，免 Python 執行期） | 0.5.0；47 dl；**授權 `statim-weights`（自訂）** | B |
| 5 | `Mapika/decider-0.8b` | [HF](https://huggingface.co/Mapika/decider-0.8b)、[GitHub](https://github.com/Mapika/decider) | 1.51 GB bf16 / 0.75B | 路由、分類、判決、瀏覽器 agent | ✅ | ✅（`decider.infer`，較慢） | 10.7k dl；家族文件完整 | B |
| 6 | `jaredpalmer/kev-0.8b`（及 4B/9B/27B） | [HF](https://huggingface.co/jaredpalmer/kev-0.8b)、[GitHub](https://github.com/jaredpalmer/kev) | adapter 43 MB ＋ Qwen3.5-0.8B base | documents/skills/devtools | ✅（ECE 0.033） | ✅（NB 級） | **7.0k★**、9k dl | B |
| 7 | `alibiserikbay/JevK5-Lite` | [HF](https://huggingface.co/alibiserikbay/JevK5-Lite)、[GitHub](https://github.com/allebee/jevk5) | 1.75 GB / 437M | 7 公開資料集（含 tweet_eval sentiment） | ✅ 校準佳 | ✅（CPU 專用） | **preview**、59 dl | B |
| 8 | `anthonym21/qwen3-0.6b-rlcd-decision` | [HF](https://huggingface.co/anthonym21/qwen3-0.6b-rlcd-decision)、[GitHub](https://github.com/anthony-maio/eve-rlcd) | 2.38 GB fp32 / 0.6B | SST5/AGNews/Emotion/多來源混合 | ✅（ECE 0.021 自報） | 🟡 需自訂 loader | 989 dl | B（有反證） |
| 9 | `mobarmg/jev-schema-scorer-deberta-v3-large` | [HF](https://huggingface.co/mobarmg/jev-schema-scorer-deberta-v3-large) | 1.74 GB / 435M | schema-conditioned 泛用（可讀入 criteria） | ✅ 分布 | ✅ | MIT；7 likes | B（無 eval） |
| 10 | `leobitz/jev-berta-base-zeroshot-classifier` | [HF](https://huggingface.co/leobitz/jev-berta-base-zeroshot-classifier) | DeBERTa-v3-base / ~184M | 零樣本分類（JEV-style API） | ✅ softmax | ✅ | MIT；**無 eval** | B（無 eval） |
| 11 | `kaivoss/system-one-270m` | [HF](https://huggingface.co/kaivoss/system-one-270m) | 0.54 GB / 268M | 合成 typed-decisions | ✅（proper scoring） | ✅ | gemma 授權；69 dl | C（合成資料） |
| 12 | `shreyanbr/system-one-zeroshot`／`-distilled` | [HF](https://huggingface.co/shreyanbr/system-one-zeroshot) | 71M DeBERTa-xsmall | 客服路由 | ✅（需 calibration.json） | ✅ | 自承弱、banking77 污染 | C |
| 13 | `Mannedood/local-system-one-student` | DecisionEval 目錄 | 149M ModernBERT-base | typed-decisions | ✅ | ✅ | MIT；未查證細節 | C |
| 14 | `ukung/bert4jev` / `rAVEUK/open-jev-deberta-v3-large` | DecisionEval 目錄／HF | 434M DeBERTa-v3-large | 同 open-jev 血統 | ✅ | ✅ | 無獨立 eval | C（重複造輪） |

> **僅列代表**。HF 上 `search=jev` 以「下載量 × 近 90 天」實查共有 **100+ 筆**命中；其中 2B 以上、
> 多模態、非英文、量化／轉檔（GGUF/MLX/ONNX/CoreML，只是同一權重的另一格式）佔絕大多數，已於上表外排除。

### 2. 值得實測的三個變體（每個一節）

#### 2.1 `fastino/GLiNER2.5-Decide`（★ 最對口的新變體）

- **它是什麼**：fastino（GLiNER 官方）在 `gliner2-large-v1` 上特化的 **340M 英文分類模型**，`AutoExtractor`
  載入；**標籤集與每個標籤的「描述」都在呼叫時才給**（schema-conditioned），單一 forward pass、**不生成 token**。
  作者原文："Pass any label set at call time: intent, routing, **sentiment**, priority, policy, and multi-label
  tags… No prompt template. No generated tokens. Load it with `AutoExtractor` and ship it locally."
- **為何對口**：
  - 官方 benchmark `fastino/fast-decisions`（17 域 × 300 held-out）**含 `review_sentiment`（negative/neutral/
    positive）與 `restaurant_review`** —— 與我們的標籤形狀逐字相同（缺 `not-discussed`，可用多標籤或加
    `other` 補）。
  - 標籤可帶描述 → 可把 R1 的 criteria 文案直接搬進來，無需重訓。
  - README 明載分類輸出可帶信心：`include_confidence=True` → `{'sentiment': {'label':'negative','confidence':0.82}}`；
    `cls_threshold` 可調。
- **資料點**：官方平均 exact-match **60.2%**（17 域），**贏過** JevK5 57.6%、GLiNER2.5-multi-Decide 56.7%、
  SemIf(Qwen3.5-4B) 56.4%、GLiFormer-large 49.0%、**Laya Router 46.6%**。Apache-2.0；`pip install gliner2[local]`。
- **未查證／風險**：(a) **沒有公布 ECE／校準數字**，也沒逐域數字（只給 17 域平均）；(b) `classify_text` 是否
 吐出**全選項機率分布**，我僅在文件看到 label＋單一 confidence，**未查證**完整分布；(c) 1.95 GB 權重（fp32），
  略超本研究「不自行下載 > 1 GB」的上限 → **交由 PM 決定是否下載實測**。

#### 2.2 `manjunathshiva/opendecider-nano`（★ 最小可下載、訓練集最貼社群）

- **它是什麼**：~400M（`jhu-clsp/ettin-encoder-400m`）的 ModernBERT 系 encoder，Apache-2.0，`pip install
  opendecider`，**0.8 GB 下載**、CPU/CUDA/MPS 都可。狀態＋typed questions → 每個選項的校準機率，單 pass、不解碼。
- **為何對口**：**訓練集含 `go_emotions`、`google/civil_comments`、`dbpedia`、CLINC、SMS spam、WNC**——
  在同族變體裡最偏「社交／情緒／評論」。作者宣稱 typed-decisions **0.796 vs Laya 0.766**（+0.030，配對 bootstrap
  95% CI +0.014~+0.044），4B 版在 200 題「沒訓練過」的一般決策上與 Jev 打平（0.735 vs 0.730）。
- **未查證／風險**：下載量極低（71 dl、2 likes、9/27 才發佈）→ 成熟度低；**沒有在 sentiment/attitude 上報數字**；
  0.8 GB 剛好在本研究「要下載的列給 PM」門檻內。

#### 2.3 `heman10x/rlcd-modernbert-151m`（★ 唯一有現成「棄答槽」、且最小的）

- **它是什麼**：151M GLiClass/ModernBERT，非自迴歸單 pass；**輸出槽含一個 `__insufficient_evidence__` 棄答
  slot**（24 個實質選項＋1 棄答），用 CE+Brier 複合損失與 L-BFGS 溫度縮放訓練；ONNX 有 **303 MB fp16** 版。
- **為何對口**：**棄答槽語意上最接近我們的 `not-discussed`**（「沒談到這個面向」≈「證據不足」）；151M 是
  同族最小、ONNX 303 MB 甚至可離線跑；作者有 JevBench 231 任務的分層數字（easy 87.5% / standard 69.4% /
  hard 36.9%，hard-tier ECE 0.118）。
- **未查證／風險**：(a) 任務域是**銀行／軟體工作流**，不是社群態度；(b) **授權有爭議**——第三方目錄
  `mrjev.com` 明指「它的 LICENSE 不被承認是 badge 上寫的 Apache-2.0」，**商業使用前必須自行核對 LICENSE 檔**；
  (c) 分層分數高（easy 87.5%）多來自 NLI 式 template（作者 v1.4 用 hypothesis 句式「It is {描述}」得來），
  我們的 state 不會長那樣。

### 3. 備選與有反證的變體（列給 PM，不建議優先）

- **`Beko2210/statim-decide-en-large`**：`convaiinnovations/laya` 的直系微調，同 ModernBERT-large 骨幹。這是
  **「如果我們要留在 laya 家族、但想修 sentiment」最直接的一條**：sentiment 零樣本 **0.6733（base 0.6200）**、
  typed-decisions 0.768（base 0.3610）、DAIR Emotion 0.588（base 0.5945，**無增益**）。缺點：**授權是自訂的
  `statim-weights`（非 Apache/MIT）**，且它是 C++ 引擎生態，與我們的 Python pipeline 要接一層。**Emotion 無增益
  是警訊**：與 R4 判讀（情緒族是天花板）一致。
- **`alibiserikbay/JevK5-Lite`**：437M DeBERTa-v3-large，主打**校準**（7 資料集 top-label ECE 0.035–0.103，
  贏 GLiNER2.5-Decide），但作者自己在卡上寫「**它是 preview，沒贏過它對標的模型**」，且 **tweet_eval sentiment
  只是平手**。→ 校準好但準確率沒突破。
- **`anthonym21/qwen3-0.6b-rlcd-decision`**：0.6B，自報 ECE 0.021、混合集準確率 0.807（含 SST5/emotion）。
  但 **arXiv 2609.24574 對它的實測是反證**：中位 ECE 0.128 看似低，**Brier 0.662、coverage–accuracy 面積
  0.505，「信心幾乎沒有排序價值」**。→ 不可拿來做 gating。
- **`Mapika/decider-0.8b` / `jaredpalmer/kev-0.8b`**：兩者都是 Qwen3.5 系 LoRA + decision head、TypeSafe
  wire format 相容、文件完整（kev 7k★）。kev-0.8b 報 ECE 0.033、OOD transfer-v4 test 0.697；decider-0.8b
  報 held-out 0.707。**但它們的評測集是「文件／工具／技能」語域**，與貼文態度無關；且 0.8B 解碼器 CPU 上比
  151M encoder 慢一個量級。→ 備選。

### 4. 商業託管版（R1 之後的新變化）

| 服務 | 端點 / 價格（實查 2026-09-30） | 對我們的意義 |
|---|---|---|
| **TypeSafe Jev 1.13（經 OpenRouter）** | `POST openrouter.ai/api/alpha/decisions`，`typesafe/jev-1.13`；**$0.042/M input，output 免費**（R1 的 $42/十億一致） | **新出現**：R1 當時查 `typesafe/jev-router` 的 `/endpoints` 是空的、無法呼叫；**現在 Jev 本體已在 OpenRouter 上可付費直呼**，且**有官方 cookbook「Classify and Tag Text at Scale with Jev」正是我們的任務形狀**（short texts、choice 類別＋每 tag 一個 noul、教人用標註樣本調門檻） |
| TypeSafe Jev（經 TeamoRouter） | `api.teamorouter.com/v1/systemone`，model `jev`；**限時促銷 99.9% off** | 第三方轉售，價格不穩、不建議當正式路線 |
| Jev Router | OpenRouter `typesafe/jev-router`，pricing = 0 | 是**模型路由**不是評分器（R1 已判不適用） |

- **成本**：Jev 一條 3 問的短 ticket ≈ 447 input tokens ≈ **$0.000019**（OpenRouter 自己的 blog 實測）。
  我們 216 則 × 6 題一次呼叫，成本量級與 R4 的 flash 表同級或更低。
- **關鍵取捨不變**：Jev **封閉權重、不可自架、不可回溯**，違反本專案「可重跑、可稽核」要求 → 只能當
  **準確率天花板對照**，不能當 v1 的 judge。

### 5. 文獻證據（這節決定判決怎麼寫）

| 文獻（查詢 2026-09-30） | 對本專案的關鍵結論 |
|---|---|
| **arXiv 2609.24574**《Evaluating Decision Models for Text Annotation in Computational Social Science》(Ibrahim & Zaki, 2026-09-23) | 在 18 個 CSS 標註任務（7,977 題、含 0.6B RLCD 決策模型）上：決策模型在 15 個任務中 **14 個輸給最強 LLM，中位差 11.6 macro-F1**；信心比 19 個 LLM 的 16 個好，但**輸給 Claude 前段（中位 ECE 0.157 vs 0.066）**；≥0.9 信心時中位準確 0.815 @ 0.376 coverage；**「empathy in peer-support dialogues」這類主觀構念：模型近亂猜卻報高信心（ECE 0.538）**。→ **這是我們任務（主觀態度）最貼的證據**：決策模型這族在主觀構念上是弱區，cascade（低信心→LLM）才是它的價值。 |
| arXiv 2609.26550《JEV-as-a-Judge》(CMU, 2026-09-22) | Jev 在偏好／有證據的事實性上與最強 judge 差 ≤3 pp、成本 0.36%；**但在「無參考文本的自由寫作」上所有受測 judge 都不可用**。→ 我們的態度判斷正屬那段警告。 |
| arXiv 2609.28940《JEV and Laya as System One Decision Layers…》(2026-09-24) | 盤點 System One 生態（含 Jev-Ultrafast）；明講 Laya 原始 ECE 0.466→溫度縮放後 0.081。屬「跨 benchmark 不能外推」的提醒。 |
| arXiv 2609.23886《The smart if-statement》/ `flock-io/this-that-model-1.0` | 1.88B typed decision；在第三方 68 題隊列上 0.941/Brier 0.042 **勝 Jev**——但那是**空間／動作決策**域，非態度；且 1.88B > 我們的 CPU 預算。 |
| **Decision 1.0**（`vllm-sr.ai/decision-paper.pdf`） | 開源家族（Kai-0.6B mmBERT、Eos-0.8B、Sol-2B、Nox-4B、Lux-9B）在共同 benchmark 上：**Jev 81.05 > Lux-9B 77.22 > Nox-4B 73.09 > Kev-9B 71.89 > Decider 2B 67.71 > Laya English 51.03 > Laya Multilingual 47.19**（Laya 墊底）。→ 再次確認「換模型有用」，但贏家仍是 ≥ 2B 或不公開權重的 Jev。 |
| **DecisionEval / Jev 實測頁** | Jev 1.13 在 `LocalLLaMA/typed-decisions` 上 accuracy 0.740、**ECE 0.045**；門檻 ≥0.7 → coverage 57.6% / acc 0.864，≥0.9 → 24.5% / 0.937。→ **Jev 的 gating 是有效的**（與 laya 的倒掛相反）。 |

### 6. 三條既有路線的交叉對照（給 PM 一眼看）

| 路線 | 對「態度」的證據 | 機率/校準 | CPU/成本 | 可稽核 |
|---|---|---|---|---|
| `open-jev-deberta-v3-large`（R4 首選） | in-domain **0.854** / OOD 0.690（**其自身域，含 SST-5 polarity**）；ECE 0.022/0.035（自報） | ✅ | ✅ 435M，1.75 GB | ✅ Apache-2.0 |
| LLM 三家 flash 多數決 | 通用強，但非專用 | ✅（自報，未驗） | 雲端；**≈ $0.11/趟** | ❌ 不可回溯 |
| hosted Jev（OpenRouter） | typed-decisions **0.740 / ECE 0.045**，gating 有效；**態度域無直證** | ✅ 且校準可信 | 雲端 $0.042/M in | ❌ 封閉 |
| **新變體（本檔 3 個 A 級）** | **均無態度域數字** | ✅（GLiNER2 全分布未查證） | ✅ 皆 CPU | ✅（除 RLCD-151m 授權） |

## 最小可用範例（可直接參考的指令／片段）

### 1. 三個 A 級變體的最小載入（**先只跑 1 則 smoke，不下載整份評測**）

```bash
# (1) GLiNER2.5-Decide：1.95 GB（>1 GB，等 PM 同意再抓）
uv venv .venv-gliner --python 3.12
uv pip install "gliner2[local]"
```

```python
from gliner2 import AutoExtractor
m = AutoExtractor.from_pretrained("fastino/GLiNER2.5-Decide")
print(m.classify_text(
    "Claude Sonnet 4 is a joy to pair with — best coding model I have used this year.",
    {"attitude": ["positive", "negative", "neutral", "not_discussed"]},
    include_confidence=True,
))   # 期望：{'attitude': {'label': 'positive', 'confidence': ~0.8}}
```

```bash
# (2) opendecider-nano：0.8 GB，CPU 可
uv pip install opendecider
```
```python
from opendecider import load
m = load("manjunathshiva/opendecider-nano")
q = {"attitude": {"type": "choice",
      "instructions": "Author's attitude toward the model discussed?",
      "criteria": {"positive": "praises/recommends",
                   "negative": "criticises/complains",
                   "neutral":  "states facts or no stance"}}}
print(m.system_one(state="<貼文>", questions=q))   # 回每選項機率（實際 API 名以專案 README 為準）
```

```bash
# (3) rlcd-modernbert-151m：ONNX fp16 303 MB 可離線
# 走 HF `model_fp16.onnx` + `clone Heman10x-NGU/Verdict-open-jev` 的 engine
```

### 2. 我們的態度題（R1 版）可直接餵給上述三者

沿用 R1 §1 的 `QUESTION`（`choice` + `positive`/`negative`/`neutral`），**只把 not-discussed 依模型調整**：
GLiNER2 用第 4 個標籤或 `multi_label`；RLCD-151m 用它的 `__insufficient_evidence__` 當 `not-discussed`。

### 3. 實查用過的 HF API（可重現）

```bash
curl -s "https://huggingface.co/api/models?search=jev&sort=downloads&direction=-1&limit=100"
curl -s "https://huggingface.co/api/models?search=decide&sort=downloads&direction=-1&limit=60"
curl -s "https://huggingface.co/api/models?search=open-jev&sort=downloads&direction=-1&limit=100"
curl -s "https://huggingface.co/api/models?filter=base_model:finetune:convaiinnovations/laya&limit=200"
# 權重檔大小（判斷可否下載）：
curl -s "https://huggingface.co/api/models/fastino/GLiNER2.5-Decide?blobs=true"
```

## 已知坑與注意事項

1. **「JEV-style」已被濫用到幾乎無鑑別度**：HF `search=jev` 有 100+ 命中，多數是**同一權重的格式轉檔**
   （GGUF/MLX/ONNX/CoreML）、**同一顆 151M／不同人重訓的同源 fork**、或**只是掛 `jev` tag 的無關模型**
   （`bigfat/jeven_loras`、`jevtor/aave-finetuned`、`jevoma4362/EuroLLM-*`）。**不要用 tag 數量當生態活躍度。**
2. **生態的公開 benchmark 全是營運決策語域**：`typed-decisions`、`fast-decisions`、`JevBench`、`sysone-bench`
   都不含「社群貼文對某 AI 模型的態度」。**任何在這個生態裡的高分，都不能外推到我們的任務**——這正是 R4
   診斷 laya「domain fit」的同一邏輯。
3. **`fast-decisions` 只公開平均、不公開逐域**：官方數字 60.2% 是 17 域平均（含 document_type、news_topic
   這些非情感域），**不能當 review_sentiment 的分數**；我們要的 review_sentiment 逐域數字**未公布**。
4. **GLiNER2 的 `classify_text` 未確認吐全分布**：文件只示範 label＋單一 `confidence`（top 機率），
   `cls_threshold` 用於多標籤門檻。**ECE 需自己算**；若它真的只給 top-1，我們的 gating 設計要重想。
5. **授權地雷**：`Beko2210/statim-decide-en-large` = 自訂 `statim-weights`（非 Apache/MIT）；
   `avbiswas/bev-decider-0.4B` = **cc-by-nc-4.0（非商用）**；`heman10x/rlcd-modernbert-151m` 被第三方目錄
   指其 LICENSE 與 badge 不符。**列為候選前逐一核對 LICENSE 檔。**
6. **低下載 ≠ 不可信，高下載 ≠ 對口**：`kev`（7k★）與 `Mapika/decider-2b`（24 萬 dl）下載量最大，但那是
   因為它們是**通用決策底座**；對我們的態度任務反而**沒有** `open-jev-deberta` 的 SST-5 血統。
7. **RLCD 縮寫歧義**：本領域的 RLCD = Reinforcement Learning for Calibrated Decisions；與 alignment 的
   RLCD（contrastive distillation）無關（arXiv 2609.24574 明講）。
8. **`typesafe/jev-router` 與 `typesafe/jev-1.13` 是兩回事**：前者是 router（pricing 0、不是評分器），
   後者才是 decision model（$0.042/M）。R1 的「查無 endpoint」是針對 router，**別誤以為 Jev 不能呼叫**。
9. **本檔未做實測**：所有 A/B 評級為「文件＋官方數字＋第三方 benchmark」的綜合判斷；**三個 A 級變體都
   還沒在我們的資料上跑過**，fit 評級是「值得測」而非「測過會贏」。

## 給 PM 的判決

### **(A) 有 3 個變體值得進入實測（列進 C7 實驗清單）**

**但前提要先講清楚**：**沒有任何變體有已證實勝過 `open-jev-deberta-v3-large` 的證據**；
`open-jev-deberta` **維持為默認 judge**，以下 3 個是「挑戰者」，各花一次 **held-out 50** 就夠（合計約
2–3 小時 CPU）：

| 優先序 | 變體 | 為什麼值得那一跑 | 要一起看的指標 |
|---|---|---|---|
| 1 | `fastino/GLiNER2.5-Decide`（340M） | 唯一**呼叫時才給標籤＋描述**、自帶 review-sentiment head、官方 17 域平均 60.2% 勝過 Laya Router | accuracy、macro-F1、**能否取得全分布**（若只得 top-1 則降級） |
| 2 | `manjunathshiva/opendecider-nano`（~400M） | 0.8 GB 最小、Apache-2.0、訓練集含 GoEmotions/CivilComments，宣稱贏 laya（0.796 vs 0.766） | accuracy、ECE、信心單調性 |
| 3 | `heman10x/rlcd-modernbert-151m`（151M） | 唯一**內建棄答槽**（直對 `not-discussed`）、ONNX 303 MB、同族最小 | **先核 LICENSE**；accuracy、棄答槽 vs 我們的 `not-discussed` 是否對齊 |

**外加一個「對照天花版」（不進實驗清單，只做一次）**：OpenRouter `typesafe/jev-1.13`（$0.042/M in），
用它的 cookbook「choice ＋ 每 tag 一個 noul」形狀，在**同一份 held-out 50** 上量一次準確率與 ECE，
當作「這個任務族在 2026-09 的商業上限」。成本 < $0.01。

### 不選 (B) 的理由（為何不是直接結案走既有路線）

純看證據，(B) 也站得住：三個挑戰者**都沒有態度域的公開數字**，而 arXiv 2609.24574 又指出決策模型這族
在主觀構念上是弱區。**但**「沒有數字」不等於「不會贏」——`GLiNER2.5-Decide` 的 sentiment head 與
`rlcd-modernbert-151m` 的棄答槽，正是 laya（與多數變體）缺的兩個結構件，值得用最小的量確認一次。
若三者都贏不過常數 baseline（R4 §C7 第 0 項，約 0.90），**直接走 R4 已建議的「LLM 三家 flash 多數決
（≈$0.11/趟）」**，並把 judge 選擇的結論寫死。

### 不選 (C) 的理由

不是「全部不可實現」：本機可跑的、授權乾淨的、安裝成本低的變體確實存在（上表 A/B 多筆皆 CPU 可跑）。

## 來源（連結 + 查詢日期）

| 來源 | 連結 | 查詢日期 |
|---|---|---|
| HF API 全站搜尋（`search=jev/decide/gliner/open-jev/rlcd/kev/systemone` 等，`sort=downloads/listModified`） | https://huggingface.co/api/models | 2026-09-30 |
| HF API 權重大小實查（`?blobs=true`） | 見 §最小範例 | 2026-09-30 |
| `fastino/GLiNER2.5-Decide`（340M、17 域平均 60.2%、Apache-2.0） | https://huggingface.co/fastino/GLiNER2.5-Decide | 2026-09-30 |
| `fastino/GLiNER2.5-Decide-1B`／`GLiNER2.5-multi-Decide` | https://huggingface.co/fastino/GLiNER2.5-Decide-1B | 2026-09-30 |
| `fastino/fast-decisions`（17 域，含 review_sentiment／restaurant_review） | https://huggingface.co/datasets/fastino/fast-decisions | 2026-09-30 |
| GLiNER2 GitHub（`classify_text`、`include_confidence`、`cls_threshold`、CPU-first、pip extras） | https://github.com/fastino-ai/GLiNER2 | 2026-09-30 |
| `manjunathshiva/opendecider-nano`（~400M、0.8 GB、Apache-2.0、0.796 vs Laya 0.766） | https://huggingface.co/manjunathshiva/opendecider-nano | 2026-09-30 |
| OpenDecider 專案與部落格 | https://github.com/manjunathshiva/opendecider 、https://huggingface.co/blog/manjunathshiva/opendecider-beats-laya-and-jev | 2026-09-30 |
| `heman10x/rlcd-modernbert-151m`（151M、棄答槽、ONNX、JevBench 分層） | https://huggingface.co/heman10x/rlcd-modernbert-151m | 2026-09-30 |
| Verdict OpenJev GitHub（v1.4 inference 修正、231 JevBench 任務） | https://github.com/Heman10x-NGU/Verdict-open-jev | 2026-09-30 |
| `Beko2210/statim-decide-en-large`（laya 直系微調；sentiment 0.673、typed-decisions 0.768；授權 `statim-weights`） | https://huggingface.co/Beko2210/statim-decide-en-large | 2026-09-30 |
| Statim 引擎 | https://github.com/BEKO2210/statim | 2026-09-30 |
| `Mapika/decider-0.8b`（0.776/0.707）與 decider GitHub | https://huggingface.co/Mapika/decider-0.8b 、https://github.com/Mapika/decider | 2026-09-30 |
| `jaredpalmer/kev-0.8b`／`kev-4b`（ECE 0.033、OOD 0.697／0.838；7k★） | https://huggingface.co/jaredpalmer/kev-0.8b 、https://github.com/jaredpalmer/kev | 2026-09-30 |
| `alibiserikbay/JevK5-Lite`（437M CPU、校準佳但 accuracy 未勝） | https://huggingface.co/alibiserikbay/JevK5-Lite | 2026-09-30 |
| `anthonym21/qwen3-0.6b-rlcd-decision`（0.6B、ECE 0.021 自報） | https://huggingface.co/anthonym21/qwen3-0.6b-rlcd-decision | 2026-09-30 |
| `mobarmg/jev-schema-scorer-deberta-v3-large`／`leobitz/jev-berta-base-zeroshot-classifier` | https://huggingface.co/mobarmg/jev-schema-scorer-deberta-v3-large 、https://huggingface.co/leobitz/jev-berta-base-zeroshot-classifier | 2026-09-30 |
| `kaivoss/system-one-270m`／`shreyanbr/system-one-*`／`cainai/OpenJev-Qwen3.5-0.8b`／`flock-io/this-that-model-1.0` | https://huggingface.co/kaivoss/system-one-270m 等 | 2026-09-30 |
| Decision-1.0 家族（Kai-0.6B／Eos-0.8B／Sol-2B／Nox-4B／Lux-9B）與論文 | https://huggingface.co/llm-semantic-router/Decision-1.0-Kai-0.6B 、https://vllm-sr.ai/decision-paper.pdf | 2026-09-30 |
| OpenRouter Jev 文件與 cookbook「Classify and Tag Text at Scale with Jev」 | https://openrouter.ai/docs/guides/community/jev 、https://openrouter.ai/docs/cookbook/evaluate-and-optimize/jev-classification | 2026-09-30 |
| OpenRouter `typesafe/jev-1.13` 定價（$0.042/M in，output free） | https://openrouter.ai/typesafe/jev-1.13 | 2026-09-30 |
| OpenRouter blog《What Is Jev?》（$0.042/M、閉源、三 primitive） | https://openrouter.ai/blog/insights/what-is-jev/ | 2026-09-30 |
| TeamoRouter Jev 轉售（促銷價） | https://teamorouter.com/docs/jev-api | 2026-09-30 |
| DecisionEval：Jev 實測（typed-decisions 0.740、ECE 0.045、gating 表） | https://decisioneval.dev/models/typesafe-jev/ | 2026-09-30 |
| DecisionEval：Jev 替代品目錄、<500M 清單、open-jev 條目 | https://decisioneval.dev/alternatives/typesafe-jev/ 、https://decisioneval.dev/models/size/under-500m/ | 2026-09-30 |
| (由 websearch 摘要取得) rohitraj.tech 開源 Jev 替代品盤點、systemonemodels.org、mrjev.com、scrapecreators comment-mining skill | https://rohitraj.tech/notes/jev-alternatives-open-weights-decision-models-2026 等 | 2026-09-30 |
| **arXiv 2609.24574** 決策模型在 CSS 標註任務的實測（最關鍵） | https://arxiv.org/abs/2609.24574 | 2026-09-30 |
| arXiv 2609.26550 JEV-as-a-Judge | https://arxiv.org/abs/2609.26550 | 2026-09-30 |
| arXiv 2609.28940 JEV/Laya as System One Decision Layers | https://arxiv.org/html/2609.28940v1 | 2026-09-30 |
| arXiv 2609.23886《The smart if-statement》／`this-that-model-1.0` | https://arxiv.org/abs/2609.23886 | 2026-09-30 |
| 現行候選（R4 已查，本檔作基準重引） | https://huggingface.co/com-kotobalabs/open-jev-deberta-v3-large 、https://github.com/kotoba-lang/typed-decisions | 2026-09-30 |
