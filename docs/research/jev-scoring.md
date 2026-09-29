# JEV 家族評分器選型與校準驗證（C3 / C5 前置）

> 研究日期：2026-09-29（實際執行於 2026-09-29 07:37–08:20 UTC+8）
> 用途：決定 C3 `score` 的逐則分類模型，並定義 C5 校準驗證怎麼做、門檻怎麼訂。
> 實驗沙箱：`/tmp/opencode/llm-arena-r1/`（不入版控，專案目錄只留本檔）。
> 本機環境：Linux、12 核 CPU、23 GiB RAM、**無 NVIDIA GPU**（`nvidia-smi` 失敗）；Python 3.12.14（uv 建立）。

## TL;DR（結論與選型建議，3 句內）

1. **選 `convaiinnovations/laya` 英文 checkpoint（HF repo root，Apache-2.0）**，用 `choice` 題型做三類態度分類（positive / negative / neutral），校準機率取 `answer_confidence = max(p)`；`pip install laya` 即可、CPU 可跑、零 output token、單則約 **0.5–0.8 秒**（本機 12 核 CPU），且套件內建 `laya-evals` 可直接算 accuracy 與 ECE。
2. **不用 AgentJev-0.6B**（需自架 HTTP server＋下載 3.9 GB 權重，且 HF 上發布的權重標示為 *coding-completion* 特化，不是通用社群情緒模型）；**不用 LLM2Jev**（它是「把任意 LLM 變成 Jev 式決策器」的框架，自己沒有權重，要自備 Qwen3.5-4B 級 base model，成本高一個數量級）；**不用 `typesafe/jev-router`**（它是「挑模型」的 router，不是評分器，OpenRouter 上 `pricing = -1` 且查詢當下 `/endpoints` 回空陣列，等於無法呼叫）。
3. **關鍵坑**：laya 出廠權重偏過度自信，且 `choice:11+` 這個 bucket 的溫度是壞的（0.1006，載入時被 clamp 成 0.5 並發 warning）；我們的三選項題剛好落在 `choice:3-5`（有效溫度 1.7602），但要記得以 `answer_confidence` 而非 `confidence` 當校準機率，並在 C5 用自己的人工標註集量 ECE。

## 選型細節（版本、理由、替代方案對比）

### 四個候選的基本資料（皆以 2026-09-29 實際查詢／下載為準）

| 項目 | `convaiinnovations/laya` | `AgentJev-0.6B` | `LLM2Jev` | `typesafe/jev-router` |
| --- | --- | --- | --- | --- |
| 類型 | 模型（weights） | 模型（weights）＋自架服務 | **框架**（需自備 base LLM） | **Router**（挑模型，非評分器） |
| 位置 | [HF `convaiinnovations/laya`](https://huggingface.co/convaiinnovations/laya) | [GitHub `malevrigns/agent-jev`](https://github.com/malevrigns/agent-jev) ＋ [HF `aimeigaoshou/agent-jev`](https://huggingface.co/aimeigaoshou/agent-jev) | [GitHub `Yinsongxu/LLM2Jev`](https://github.com/Yinsongxu/LLM2Jev) | [OpenRouter `typesafe/jev-router`](https://openrouter.ai/typesafe/jev-router) |
| 版本（實查） | pip `laya==0.3.21`；HF revision `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851` | repo commit `a965ca8ff06ccabc0c796dca5447b55cc2069cee`；HF revision `0e2593e6e6c0eade0700712ac13c4389aa7654cc` | 無 release tag（git clone main） | OpenRouter 目錄項，`created` 1790363560 |
| 安裝 | `pip install laya`（Python ≥ 3.10） | clone repo ＋ `pip install -r requirements.txt` ＋ HF 下載 | `uv sync --extra sglang\|transformers\|mlx` | 無（呼叫 API） |
| 推論 API | `laya.load()` / `Router().predict()`，或 `laya-serve` HTTP（`POST /v1/systemone`） | `python -m jev_service.server`，再打 `POST /api/evaluate` | `LLM2Jev(backend=...).evaluate(JevRequest)`，或 `llm2jev-serve` | `POST https://openrouter.ai/api/v1/chat/completions` |
| 輸入／輸出 | state ＋ typed questions（`choice`/`score`/`noul`）→ 每個選項的機率分布 | state ＋ typed questions（Boolean/Choice/Score）→ 分布 | 同 Jev request 形狀（Choice/Score/Noul） | 一般 chat messages → **文字** |
| 授權 | Apache-2.0 | Apache-2.0（程式與權重） | Apache-2.0 | 專有／託管 API |
| 本地可跑 | ✅ CPU 可（本機已跑通） | ✅ 理論上可（CPU 需自測） | ✅ 但需自備 4B 級 LLM，實務上要 NVIDIA GPU | ❌ 純雲端 |
| 下載量 | **842.6 MB**（英文 checkpoint 單檔） | `model.safetensors` **2393.7 MB**（FP32）＋ Qwen3-0.6B **1503.3 MB** | 另加 base LLM（範例 Qwen3.5-4B） | 0 |
| 單則成本（本地） | ~0（實測 0.53–0.77 s/則） | ~0（0.6B，但需常駐 server） | ~0 但每則要跑 4B forward | 付費；`typesafe/jev-router` 定價 `-1`（動態），**實查無 serving endpoint** |
| 輸出校準機率 | ✅ 每選項機率 ＋ `answer_confidence` | ✅ 每選項機率（`temperatures.json` 校正） | ✅ 由 yes/no logits 算機率 | ❌ 回傳文字，無結構化機率 |
| 內建評測工具 | ✅ `laya-evals`（accuracy / ECE / slice） | ❌ 需自己寫 | 🟡 有 `jevbench` 但綁他們的 benchmark | ❌ |
| 社群規模（約略） | HF 4.3k like、12 adapters、94 finetunes、51 spaces | GitHub 321★、HF 35 like、821 downloads/mo | GitHub 367★ | — |

### 最終選擇：`convaiinnovations/laya` 英文 checkpoint（pin `revision`）

**理由**

1. **唯一一個「今天就能在本機 CPU 跑通、且直接吐校準機率」的候選**——本筆記的所有實測輸出都來自它（見下節）。
2. **零 output token 解碼**：不會有 JSON parse 失敗、不會有幻覺文字，機率直接來自 softmax。
3. **套件內建 `laya-evals`**，把 C5 要的 accuracy／ECE／切片（tag、model、qid）變成一行 CLI，不用自己造輪子；ECE 公式與 bin 邊界也已是套件內的 `laya.common.ece_score`。
4. **授權 Apache-2.0、可完全離線**：C2/C3 大量逐則評分，自架才能控制成本與可重現性（plan.md 技術選型已如此定調）。
5. **我們的三選項題落在 `choice:3-5` bucket，該 bucket 有合理擬合溫度 1.7602**（見「已知坑」）。

### 為什麼不是其他兩個

- **不是 `AgentJev-0.6B`**：
  - **兩份官方文件對「這份權重是什麼」說法互相矛盾**，這本身就是選型風險：HF model card 開頭寫
    *"This file is the coding-completion checkpoint. It reads the task, the code, and the checks that
    were shown, then returns a probability that the work is actually finished."*，主指標是「executed
    coding pairs 準確率 57.8%」；而 GitHub README 的 typed-decisions 表列 AgentJev **79.25%**，
    並說 *"The benchmark checkpoint selected for the table above was step 600. These published
    tensors are that run."* 兩邊指的是同一批發布權重，卻給出不同的定位與分數。即使取對自己
    有利的 79.25% 版本，它的 benchmark 仍是 invoice/customer-service/security/agent-trace 四種
    **工作流程決策**，不是「社群貼文對某模型的正負面態度」，屬於用途錯配。
  - 工程成本高：要 clone repo、下載 2.4 GB FP32 權重 ＋ 1.5 GB Qwen3-0.6B、`torch.save` 包一次、長駐 port 8149 的 server。laya 是一行 `pip install`。
  - **laya 在 agent-jev 自己的 benchmark 上也已經贏**：agent-jev README 的 Latency 表列「Laya 421M 單則 41.53 ms vs AgentJev 598M ~60–70 ms（短輸入）」，而 top-1 兩者同級（79.25% vs 77.00%）。在「短社群貼文」這個情境，laya 更快、更小、部署更簡單。
  - 唯一的優勢是 2048 token context 與寬候選集（64+ 選項）下的 shared-prefix 加速——我們只有 3 個選項、貼文多半 <320 token，用不到。
  - 本機實測確認下載／啟動可行，但啟動成本與伺服器複雜度明顯較高（見文末「AgentJev-0.6B 實測嘗試」）。
- **不是 `LLM2Jev`**：
  - 它**不是模型**。README 第一句：*"Turn local language models into Jev-style structured decision models."* 它需要你自備一個 HF-compatible causal LM（官方範例用 **Qwen3.5-4B**，JevBench 76.2% accuracy）。
  - 官方 Quick Start 是 `uv sync --extra sglang` ＋「Linux with a supported NVIDIA GPU」。CPU 雖有 `TransformersBackend`，但跑 4B 模型逐則評分在本機（無 GPU、23 GiB RAM）不現實，且成本比 421M 的 laya 高約一個數量級。
  - 它的價值在於「你已經有想用的本地 LLM，想讓它不用 decode 就吐機率」；我們沒有這個前提，直接用現成的 laya 更省事。
- **不是 `typesafe/jev-router`**：
  - 它是 **router**：OpenRouter 描述為 *"Jev Router picks the best model and reasoning effort for each request"*，輸出是**文字**，不是機率分布。用它做量產評分等於拿路由表當溫度計。
  - `GET /api/v1/models` 實查其 `pricing.prompt` = `"-1"`、`pricing.completion` = `"-1"`（動態定價，不是真價格，OpenRouter 文件明載 `-1` 代表動態）；`GET /api/v1/models/typesafe/jev-router/endpoints` 實查回 `"endpoints": []`，**查詢當下沒有 provider 在服務它**。
  - 補充：TypeSafe 真正的評分模型是託管的 **Jev**（封閉權重），官網標價 **$42 / 十億 input tokens**（≈ $0.042 / 1M，與 laya README 引用的 $0.042/1M 一致）。便宜、也確實回傳 calibrated confidence，但封閉權重、無法自架、無法審核，違反本專案「可重跑、可回溯」的要求，因此 v1 不用。

### 具體選型參數（C3 直接照抄）

| 參數 | 值 | 來源 |
| --- | --- | --- |
| model id | `convaiinnovations/laya`（subfolder 不指定 = 英文 checkpoint） | 實測 |
| pin revision | `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851` | HF API 實查 |
| `meta.judge.model` | `"laya"` | plan.md schema v1 |
| `meta.judge.revision` | 上面的 sha（前 7 碼 `55cf4c4` 也可，但建議存完整 sha） | — |
| `meta.judge.calibrated` | C5 通過前填 `false`，通過後改 `true` | — |
| 題型 | `choice`，3 個選項 | 實測 |
| 類別標籤 | `positive` / `negative` / `neutral` | plan.md evidence schema |
| 校準機率欄位 | `answer_confidence`（= `max(probabilities)`），**不是** `confidence` | 實測＋套件 docstring |
| context | `max_len=512`、`head_max_len=192` → state 實際可用約 **320 tokens** | `rl_agent_config.json` 實查 |
| 裝置 | `device="cpu"`（本機無 GPU） | 實測 |

### evidence / `scores.json` 欄位對應（C3 直接照填）

| schema 欄位 | 從哪來 | 說明 |
| --- | --- | --- |
| `evidence[].label` | `answers.<qid>.choice` | 三類之一（`positive`/`negative`/`neutral`） |
| `evidence[].prob` | `answers.<qid>.answer_confidence` | **就是 `max(p)` 的那個機率**；不要填 `confidence` |
| `evidence[].judge` | 常數 | 建議 `laya@55cf4c4`（沿用 plan 的 `<model>@<sha>` 慣例，sha 取前 7 碼即可） |
| `scores.meta.judge.model` | 常數 | `"laya"` |
| `scores.meta.judge.revision` | 常數 | `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`（建議存完整 sha） |
| `scores.meta.judge.calibrated` | C5 結果 | 通過前 `false`，通過後 `true` |
| `scores.models[].positiveRate` | 由 `label` 數 | `#positive / sampleSize`（C4） |
| `scores.models[].confidence` | **C4 決定** | 建議別直接用 `mean(prob)`：那會把「模型有多激動」和「評分器有多確定」混在一起。建議用 `positiveRate` 的 **Wilson 95% 信賴區間下界**（樣本數少時會自然變小，語意清楚）；若要顯示評分品質，另存 `mean(answer_confidence)` 到 `meta.notes` 或新欄位。此事需與 `jason-lab` 同步 schema。 |

> 送評時 state **只放貼文原文，不放模型名**——laya 的題目問的是「這則貼文對某個 AI 模型的態度」，
> 不需要知道是哪個模型；不給名字同時滿足了 plan 要求的「送評時遮蔽模型名」。
> 但這也表示：**一則同時談多個模型的貼文會被併成單一態度**，歸屬由 C2 的 `modelId` 決定；
> C2 若發現貼文提及多個模型，應拆成多筆或排除。

## 最小可用範例（可直接參考的代碼片段／指令）

### 0. 安裝（本機實際執行）

```bash
mkdir -p /tmp/opencode/llm-arena-r1 && cd /tmp/opencode/llm-arena-r1
uv venv --python 3.12
# 本機沒有 GPU，必須指定 CPU 版 torch，否則會下載 ~1.5 GB 的 CUDA wheel
uv pip install laya --torch-backend=cpu
```

實際結果：

```
+ torch==2.14.0+cpu
+ transformers==5.17.0
+ laya==0.3.21
$ .venv/bin/python -I -c "import laya; print('laya', laya.__version__)"
laya 0.3.21
$ .venv/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
2.14.0+cpu False
```

> `laya[serve]`（HTTP server）、`laya[onnx]`（ONNX Runtime，純 CPU 部署可用）是選配。

### 1. 三類態度分類：5 則假貼文（實際執行輸出）

題目定義（這是 C3 要用的核心 prompt，**不要**把模型名塞進 state，避免自我偏袒）：

```python
QUESTION = {
    "attitude": {
        "type": "choice",
        "instructions": "What is the author's overall attitude toward the AI model discussed in this post?",
        "criteria": {
            "positive": "The author praises the model, recommends it, or is clearly satisfied.",
            "negative": "The author criticises the model, complains about it, or prefers an alternative.",
            "neutral": "The author states a fact, asks a question, or has no clear positive or negative stance.",
        },
    }
}
```

程式：

```python
import laya

agent = laya.load("convaiinnovations/laya")           # 首次會下載 ~842 MB
res = agent.predict({"post": post_text}, QUESTION)
ans = res["answers"]["attitude"]
print(ans["choice"], ans["probabilities"], ans["answer_confidence"])
```

5 則貼文與**實測輸出**（`/tmp/opencode/llm-arena-r1/demo.py`）：

| # | 貼文（節錄） | label | positive | negative | neutral | answer_confidence |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Claude Sonnet 4 is a joy to pair with… Best coding model I have used this year. | positive | **0.9436** | 0.0155 | 0.0409 | 0.9436 |
| 2 | Honestly disappointed in GPT-5… I am switching back to my old setup. | negative | 0.0152 | **0.9517** | 0.0331 | 0.9517 |
| 3 | Gemini 2.5 Pro is priced at $1.25 per million input tokens… | neutral | 0.1105 | 0.0819 | **0.8076** | 0.8076 |
| 4 | Llama 4 is cheap and fast, but instruction following is hit or miss… | positive | **0.6291** | 0.1072 | 0.2637 | 0.6291 |
| 5 | Does anyone know whether Grok 4 supports function calling…? | neutral | 0.1332 | 0.1165 | **0.7503** | 0.7503 |

原始 JSON（case 1，完整 schema）：

```json
{
  "model": "laya-rl-agent",
  "answers": {
    "attitude": {
      "type": "choice",
      "choice": "positive",
      "probabilities": {"positive": 0.9436, "negative": 0.0155, "neutral": 0.0409},
      "confidence": 0.7724,
      "answer_confidence": 0.9436,
      "action": {"act_probability": 1.0}
    }
  },
  "usage": {"input_tokens": 127, "output_tokens": 0}
}
```

注意 **`confidence` 與 `answer_confidence` 是兩個不同東西**：`confidence` 對 `choice` 是
「1 − 正規化熵」（衡量分布集中度，與選項數有關），`answer_confidence` 才是「回報答案的機率
＝ `max(p)`」，也是溫度縮放擬合與 ECE 計算用的量。**校準與 gating 一律用 `answer_confidence`。**

效能（本機 CPU，實測）：

- checkpoint 冷載入（含首次下載＋建構）：**113.8 s**；之後同一 process 內單則 **658–768 ms**。
- `predict_batch` 12 則一輪：**6317 ms（526 ms/則）**，省下約 1.3×。
  官方在 GPU 上宣稱 batching 有 9–10× 加速，文件也明載「On CPU, increasing batch size alone may
  not speed up inference」——**CPU 上不要對 batching 期待太高**。
- `usage.output_tokens` 永遠是 `0`（不解碼）。

### 2. `laya-evals`：C5 的 accuracy／ECE 一行搞定（實際執行）

先寫一個 JSONL 標註集（格式見下節），然後：

```bash
.venv/bin/laya-evals validate smoke.jsonl
# -> 12 examples, 1 question id(s): attitude

LAYA_DEVICE=cpu .venv/bin/laya-evals run smoke.jsonl --model english --device cpu \
  --min-accuracy 0.8 --max-ece 0.15 \
  --markdown report.md --json report.json
```

實測輸出（12 則手寫、故意全部明顯，**這不是真正的校準，只是流程示範**）：

```
choice_accuracy           1.0000
cost_per_decision_p50_ms  719.7626
cost_per_decision_p95_ms  8583.8498
ece                       0.1210
latency_p50_ms            719.7626
latency_p95_ms            8583.8498
mean_confidence           0.8790
```

`report.md` 的切片（`--slice` 可加 `tag`/`language`/`model`/`qid`）：

| tag | choice_accuracy | ece | mean_confidence |
| --- | --- | --- | --- |
| hn | 1.0000 | 0.1285 | 0.8715 |
| reddit | 1.0000 | 0.0957 | 0.9043 |
| x | 1.0000 | 0.1533 | 0.8467 |

**怎麼讀這組數字**：12 則全對，但平均信心 0.879 → ECE = 1 − 0.879 = **0.121**（因為全對時
ECE 退化為 `1 − mean(confidence)`）。這正是「出廠偏過度自信」的訊號；真實的 100–200 則
標註集會有錯誤，ECE 才有完整意義。

### 3. 逐則評分的 JSONL 標註集格式（C5 直接照用）

`laya.evals` 的 `Dataset.from_jsonl` 契約（實查原始碼）：每行一個 object，必填
`state` / `questions` / `expected`；選填 `tags`、`language`、`model`。

```json
{"state": {"post": "Claude Sonnet 4 is the best coding model I have used."}, "questions": {"attitude": {"type": "choice", "instructions": "What is the author's overall attitude toward the AI model discussed in this post?", "criteria": {"positive": "The author praises the model, recommends it, or is clearly satisfied.", "negative": "The author criticises the model, complains about it, or prefers an alternative.", "neutral": "The author states a fact, asks a question, or has no clear positive or negative stance."}}}, "expected": {"attitude": "positive"}, "tags": ["reddit"], "language": "en"}
```

`expected` 的 key 必須是 `questions` 裡有的 id（打錯會 `EvalError` 指名行號）。

### 4. 環境注意：`USE_TF=0`

官方提醒：若環境同時裝了 TensorFlow，`laya.load()` 可能卡死（transformers import 時探測 TF 造成
abseil deadlock）。本機沒裝 TF，未遇到。CI 建議直接 `USE_TF=0`。

## 校準驗證方法（C5 照著做，不必再查）

### 步驟 1：從 evidence 抽樣出人工標註集

**抽樣設計（分層抽樣，不是隨機抽）**

1. 從 `data/evidence/*.jsonl` 先過濾掉：轉貼/去重後的重複、純 URL、少於 ~10 字的碎片。
2. 依 **`source`**（reddit / x / hn）分層，各層按近 30 天貼文數比例分攤，每層至少 25 則。
3. **刻意對低信心區加權**：模型的錯誤集中在低 `answer_confidence`，校準曲線的誤差幾乎都來自
   低信心 bin。抽樣時對 `answer_confidence < 0.70` 的貼文抽 2–3 倍的量，其餘隨機。
4. 目標 **n = 150**（下限 100、上限 200；理由見步驟 5）。
5. 把抽出的貼文寫成一份**標註工作檔**（放 `data/calibration/` 或在沙箱），欄位：
   `hash, modelId, source, url, postedAt, text, gold(=空), notes(=空), annotator(=空), annotatedAt(=空)`。
   **不要**在裡頭放模型的預測 label/prob（避免 anchoring；要對照時用 `hash` join 回去）。

**標註指南（先寫成 `docs/annotation-guide.md` 並凍結，否則標註集不能用）**

- 先問：**這則貼文在講哪個模型？** 若主體是「用模型的人」、「模型公司」而不是模型本身 →
  標 `neutral` 並在 `notes` 記 `off_target`（實測 laya 會把「Claude 使用者很煩，模型本身還行」
  判成 negative，見「已知坑」）。
- `positive`：讚美、推薦、表達滿意、說比替代品好、說值得花錢。
- `negative`：批評、抱怨、說比替代品差、說要換掉、退款/退訂。
- `neutral`：陳述事實、問問題、轉貼、比較但未表態（「A 比 B 便宜」）、純發布消息。
- 邊界案例（要在指南明寫決定）：
  - **諷刺**：「Oh great, it hallucinated again」→ 語意是 negative（實測 laya 判 positive 但
    只給 0.4675 信心，低信心可被 gate 擋下，見「已知坑」）。
  - **混合語氣**：以主要語氣為準；真的各半 → 記 `mixed`，C5 計算時排除或算 neutral（選一個並寫死）。
  - **否定句**：「I can't recommend it enough」→ positive（實測 laya 正確）。
- 標註者只看貼文，**不看模型預測**。
- 單人標註（jason）。若行有餘力，請第二人重標 30 則，算 Cohen's κ，**κ ≥ 0.7** 才認為指南可操作；
  κ 太低代表類別定義有問題，先改指南再重標。

### 步驟 2：跑評測，拿 accuracy 與 ECE

```bash
LAYA_DEVICE=cpu .venv/bin/laya-evals run data/calibration/gold-2026-10-14.jsonl \
  --model english --device cpu --batch-size 16 \
  --min-accuracy 0.80 --max-ece 0.10 \
  --slice tag \
  --markdown docs/calibration-report.md --json docs/calibration-report.json
```

- `--slice` 的合法值是 **`language` / `model` / `qid` / `tag`**（沒有 `source`）。要按來源切片，
  就在 JSONL 每行的 `tags` 裡放來源名（例如 `["reddit"]`），再用 `--slice tag`。
- 用 `--baseline report.json --tolerance choice_accuracy=0.02` 可以拿舊報告當門檻做回歸測試。
- 離開碼：**0 通過、1 門檻未達、2 用法錯誤**——可直接當 CI gate。實測驗證：
  `--min-accuracy 1.5` → exit 1；`--max-ece 0.01` → exit 1；`--min-accuracy 0.9 --max-ece 0.2` → exit 0。
- `--min-accuracy` / `--max-ece` 是 C5 的上線門檻，值寫在這一節，不要散在別處。
- 建議同時輸出 markdown（給人看）與 json（給程式比對、當 `--baseline` 用）。

### 步驟 3：指標怎麼算（公式，C5 要能自己重現）

**(a) 準確率**

```
accuracy = 正確則數 / 總則數
```

三類建議**同時**報 **macro-F1** 與混淆矩陣，因為社群貼文類別不平衡（neutral/positive 通常
多於 negative），單看 accuracy 會騙人。`laya-evals` 給的是 `choice_accuracy`；macro-F1 用
`sklearn.metrics.f1_score(average="macro")` 自己補。

**(b) 校準曲線 / ECE**

用 `answer_confidence = max(p)` 當信心，`correct = (argmax == gold)`。
`laya` 內建公式（`laya/common.py::ece_score`，實查原始碼），等寬 bin：

```
edges = linspace(0, 1, bins+1)
ECE = Σ_i (|bin_i| / N) · |mean(conf in bin_i) − mean(correct in bin_i)|
```

- `bins` 預設 15，但**n=150 時 15 bins 每格只有 10 則，太吵**。C5 請用 `bins=5`（30 則/bin）
  畫 reliability diagram，並用 `bins=5` 報 ECE；若要跟別人的 15-bin 數字比再另外跑一次。
- 也可以直接呼叫：

```python
from laya.evals import ece          # confidences, corrects -> float
from laya.common import ece_score   # numpy 版，可指定 bins
```

**(c) Reliability diagram（畫出來）**

每個 bin 一列：`bin 範圍, n, mean_confidence, accuracy, gap = accuracy − mean_confidence`。
完美校準時 `gap` 全部 ≈ 0。本筆記附的手算版本在
`/tmp/opencode/llm-arena-r1/calib_smoke.py` 的 `ece_and_reliability()`，可參考。

**(d) 單調性檢查（gating 能不能用）**

把標註集依 `answer_confidence` 排序切 3 段（例如 <0.7 / 0.7–0.9 / >0.9），看每段的 accuracy
是否**單調遞增**。若不是單調，代表信心沒有排序能力，`min_confidence` gating 不可用（即使 ECE 好看）。
背景：arXiv 2609.26550（JEV-as-a-Judge）證明「接受高信心、升級低信心」的 cascade 能保留
99% 準確率，但前提就是信心要有排序能力。

### 步驟 4：不達標時的溫度縮放（已驗證可注入）

laya 的機率是 `softmax(logits / temperature)`。出廠的 `temperature_by_options`（`rl_agent_config.json`，實查）：

```jsonc
{
  "choice:2":   1.9063563346862793,
  "choice:3-5": 1.7601518630981445,   // <- 我們的三類題用這個，是合理的擬合值
  "choice:6-10":1.0000158548355103,
  "choice:11+": 0.10058280825614929,  // <- 壞的：載入時被 clamp 成 0.5 並發 RuntimeWarning
  "score:3-5":  1.2514300346374512,
  "noul:2":     1.983399510383606
}
```

- bucket 命名規則：`<question type>:<選項數區間>`，`2 / 3-5 / 6-10 / 11+`（`laya/common.py::temp_bucket`）。
- **我們的三類題用 `choice:3-5`，出廠值 1.7602 是有效的**——這是選 3 類而非 11+ 類的附帶好處。
- 載入時 temperature 會被 clamp 到 `[0.5, 5.0]`，無效值用 `1.0`，並發警告到 stderr。看到那行
  warning 只代表 `choice:11+` 壞掉，**不代表我們的 3 類題壞掉**（實測：3 類題輸出正常）。
- 重新擬合後注入（**已實測有效**，改完下一次 `predict` 立即生效）：

```python
agent = laya.load("convaiinnovations/laya")
agent.temperature_by_options["choice:3-5"] = T   # T 由 held-out 標註集 minimize NLL/ECE 求得
```

  實測驗證（同一則貼文，只改 T）：

  | T | positive | negative | neutral | answer_confidence |
  | --- | --- | --- | --- | --- |
  | 出廠 1.7602 | 0.1406 | 0.2121 | 0.6472 | 0.6472 |
  | 1.0 | 0.0563 | 0.1162 | 0.8275 | 0.8275 |
  | 3.0 | 0.2118 | 0.2696 | 0.5187 | 0.5187 |
  | 6.0 | 0.2708 | 0.3055 | 0.4237 | 0.4237 |

  > T > 1 讓分布更平（更不自信）；T < 1 更尖。請在 `[0.5, 5.0]` 內取值，與出廠 clamp 規則一致。
  > 注意：直接改 attribute 不會再被 clamp（實測 T=6.0 生效），所以**自己守住範圍**。

- 擬合方法：在**另一份** held-out 標註集（不是 C5 那份，避免調參污染）上，對
  `choice:3-5` 掃 T ∈ [0.5, 5.0]，取 NLL 或 ECE 最小者。`laya` 官方 fine-tune notebook 也是
  「one temperature per type」的做法。
- 擬合完把 T 寫進 C3 的設定，並在 `docs/` 記錄擬合日期與資料集 hash，因為**這是一個會影響
  所有歷史分數的參數**（改了要重跑 `score` 並發新資料）。

### 步驟 5：樣本數為什麼是 150（給 C5 一個可寫進文件的理由）

- 三類、二項式近似。若真實準確率 p ≈ 0.85：
  - n = 100 → 95% CI 半寬 ≈ **±7.0 pp**
  - n = 150 → ≈ **±5.7 pp**
  - n = 200 → ≈ **±5.0 pp**
  （`1.96 × sqrt(p(1−p)/n)`；p=0.85, n=150：`1.96 × sqrt(0.1275/150) = 5.7pp`。）
- 我們要判的是「accuracy 是否 ≥ 0.80」這種門檻，且要能偵測 0.80 vs 0.85 的差異 → n=150 足夠；
  n=100 的 ±7 pp 會讓 0.80 門檻的判定在邊緣反覆。**上限 200 是因為人工標註人力**，再上去邊際效益小。
- ECE 的 bin 數要跟 n 匹配：**n=150 → 用 5 bins**（30 則/bin，每格估計才穩）。不要用預設 15 bins。
- 若之後要做 **per-source** 或 **per-model** 切片（`--slice`），每個切片要有各自的 n；
  切片 n < 30 的數字只能參考，不要據以下結論。

## 已知坑與注意事項

1. **`confidence` ≠ `answer_confidence`**（最容易錯的一點）。`confidence` 對 `choice` 是
   1 − 正規化熵；校準與 gating 必須用 `answer_confidence = max(p)`。已實測印證：
   case 1 `confidence=0.7724` 但 `answer_confidence=0.9436`。
2. **出廠偏過度自信**。官方明載 base checkpoint 的 raw ECE 0.213（英文）；本機 12 則全對的
   簡易測試 ECE 0.121。C5 一定要在**自己的資料**上量 ECE，不要引用官方數字。
3. **`choice:11+` 溫度是壞的**（0.1006 → clamp 0.5），載入時發
   `RuntimeWarning: this checkpoint ships invalid temperatures… Treat confidence from the affected
   entries as uncalibrated.`。這行 warning **不要當成致命錯誤**，它只影響 11 個選項以上的題目。
   我們的三類題不受影響。CI 若把 stderr 當錯誤，記得過濾。
4. **不要用 boolean 字樣的選項標籤**（`true`/`false`、`yes`/`no`）——官方明載模型可能跟標籤
   而非描述走。用 `positive`/`negative`/`neutral` 這種語意標籤（我們就是這樣）。
5. **否定／歸屬錯誤仍會發生**。實測 8 個 probe：

   | probe | 預期 | 實測結果 | 判讀 |
   | --- | --- | --- | --- |
   | "I can't recommend… enough" | positive | positive 0.933 | ✅ |
   | "not bad at all" | positive | positive 0.949 | ✅ |
   | "not a fan" | negative | negative 0.959 | ✅ |
   | "hardly the improvement" | negative | negative 0.844 | ✅ |
   | **「Claude 使用者很煩，模型本身還行」** | neutral | **negative 0.824** | ❌ **歸屬錯誤**：把對社群的意見算到模型頭上 |
   | **諷刺「Oh great, it hallucinated again」** | negative | **positive 0.468** | ❌ 錯，但**信心只有 0.47** → 可被 gate 擋下 |

   結論：**錯誤不會消失，但低信心 + gating 可以截掉大部分**。C5 的單調性檢查就是在驗這件事。
   C2 收集端若能先過濾「主體不是模型」的貼文會更好。
6. **長文會被靜默截斷**。英文 checkpoint `max_len=512 − head_max_len=192` ≈ **320 tokens** 的
   state 預算；超過就取第一個視窗、其餘丟掉。Reddit 長留言要小心。
   - 緩解：C2 就截斷（例如 1200 字元）並記錄 `truncated`，C5 用 `--slice tag=long` 單獨量長文
     子集的 ECE。
   - **不要**用 `predict_long` 來「救」長文：官方明載它回傳的是「決定性視窗的機率，
     **不是整份文件的校準機率**」，會直接破壞 C5 的校準前提。
7. **語言**：英文 checkpoint 對非拉丁文字會崩（官方舉例 Khmer 0.000 accuracy 但信心 0.952）。
   `Router` 會自動分流到 `laya-multilingual`，但 **`laya-multilingual` 出廠完全沒有擬合溫度**
   （官方明載），校準更差。
   **v1 建議：pin 英文 checkpoint**（符合已凍結的 `meta.judge.model = "laya"`），並在 C2
   記錄語言、把非英文貼文排除或隔離。若之後要納入多語，用 `Router()` 並在 evidence 的
   `judge` 欄位寫 `laya-multilingual@<sha>`（兩個 checkpoint 在同一個 HF revision 裡，sha 通用），
   但**必須重跑一次 C5**，且要在 `meta.notes` 說明 judge 不是單一 checkpoint。
8. **`action.act_probability` 沒有訊號**（官方 issue #185：幾乎永遠 1.0）。不要拿它當 gate，
   用 `answer_confidence`。實測也看到它固定 `1.0`。
9. **確定性／可重現**：同 process 內重跑同一則分數一致。但 batch 大小不同可能造成微小浮點
   差異（官方明載），決策在門檻邊緣時可能翻面。C3 的「可重現」驗收請固定 `batch_size`。
10. **不用 HF inference providers**：HF 頁面顯示此模型「isn't deployed by any Inference Provider」，
    只能自架或找社群 space。
11. **`USE_TF=0`**（見上）。
12. **license 是 Apache-2.0**，商用 OK；但這不是法律意見，要發佈資料前仍請確認 model card 條款。

## 尚待 C5 產出的東西（本檔未含）

- 真正的 100–200 則人工標註集與其上的 accuracy / ECE / reliability diagram 數字。
- `choice:3-5` 的重新擬合 T（若 ECE 未達標）。
- 本檔的 12 則 smoke set、8 個 probe 是**流程驗證用**，不構成任何校準主張。

## 來源（連結 + 查詢日期）

| 來源 | 連結 | 查詢日期 |
| --- | --- | --- |
| laya HF model card（安裝、API、calibration、honest limits、benchmarks） | https://huggingface.co/convaiinnovations/laya | 2026-09-29 |
| laya GitHub README（calibration 節、fine-tuning、CLI、evals、serve） | https://github.com/NandhaKishorM/laya | 2026-09-29 |
| laya PyPI | https://pypi.org/project/laya/ | 2026-09-29 |
| laya 官方文件站 | https://nandhakishorm.github.io/laya/ | 2026-09-29 |
| AgentJev GitHub repo（latency、typed-decisions、HTTP、primitives） | https://github.com/malevrigns/agent-jev | 2026-09-29 |
| AgentJev HF model card（「coding-completion checkpoint」敘述、檔案大小） | https://huggingface.co/aimeigaoshou/agent-jev | 2026-09-29 |
| LLM2Jev GitHub（framing、Quick Start、backend、JevBench） | https://github.com/Yinsongxu/LLM2Jev | 2026-09-29 |
| LLM2Jev usage / installation / jevbench 文件 | https://github.com/Yinsongxu/LLM2Jev/blob/main/docs/usage.md 等 | 2026-09-29 |
| OpenRouter `typesafe/jev-router` model 頁與 `/llms.txt` | https://openrouter.ai/typesafe/jev-router | 2026-09-29 |
| OpenRouter `/api/v1/models` 與 `/models/typesafe/jev-router/endpoints`（實 curl） | https://openrouter.ai/api/v1/models | 2026-09-29 |
| TypeSafe 官網（Jev 定位、$42/十億 input tokens、calibrated confidence） | https://typesafe.ai/ | 2026-09-29 |
| JEV-as-a-Judge 論文（cascade、低信心集中錯誤） | https://arxiv.org/abs/2609.26550 | 2026-09-29 |
| 本機實測沙箱（程式與原始輸出，不入版控） | `/tmp/opencode/llm-arena-r1/` | 2026-09-29 |
