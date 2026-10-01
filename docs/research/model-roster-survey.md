# 社群 LLM 模型清單掃描（以 X/Twitter 為準）

> 研究日期：2026-10-01｜資料池：`data/evidence/2026-09-29.jsonl`（216 筆，其中 `source=="x"` 55 筆）
> 用途：為 `llm-arena` 更新 `config/models.yaml` 與收緊歸屬規則提供依據。
> 方法：一次性唯讀掃描腳本 `/tmp/opencode/scan_models.py`、`/tmp/opencode/final3.py`（未進專案）。
> **清單內每個模型的入選理由一律以 X 池證據為準**；全景（§5 的 OpenRouter id）僅供補齊格式，不作為熱度證據。

## TL;DR（結論與選型建議，3 句內）

1. X 池（55 筆）的討論高度集中在新一代：`Sonnet 5.5`（12 筆）、`Grok 4.7`（11）、`GLM 5.3 系列`（11，含 Prime 7）、`Opus 5.5`（9）是四大熱點；現行清單的 `Claude Sonnet 4`（X 提名 1 筆、且**0/2 筆真的在講它**）與 `OpenAI GPT-5`（X 提名 2 筆、**僅 1/7 筆真的在講它**）已被更新版本完全淹沒，是張冠李戴最嚴重的兩席。
2. X 池樣本數**不代表真實熱度**：引擎 default depth 硬上限 `per_stream_limit=12`／`pool_limit=40`，且 X 每次查詢最多只抓 2 個 subquery（`MAX_SOURCE_FETCHES["x"]=2`），所以每個模型都停在 20~35 筆、「各模型 20~35 筆」是截斷造成的假平均（證據見 §4）。
3. 建議：清單以「X 池精確提及 ≥3 筆」為入選門檻（§5 兩案並陳）；歸屬規則需收緊並加 alias map（§6），優先處理 OpenAI（GPT-5/5.5/5.6/6 世代）與 Anthropic（Sonnet 4/4.5/5/5.5、Opus、Fable/Mythos）兩個家族。

---

## §1 掃描方法與正則清單

### 方法

1. 讀 `data/evidence/2026-09-29.jsonl`，篩 `source == "x"`（55 筆）。
2. 對每筆 `text` 做**大小寫無關**的「家族＋版本號」正則掃描；一筆提到多個模型時**每個都計一次**（故各組合出現數可加總超過 55）。
3. 另做「品牌字出現、但同一家族版本號未出現」的統計（§3），衡量無法精確歸屬的量。
4. 對現行 8 模型，另檢查「該模型自己的版本字是否真的出現在被歸屬的貼文裡」（§2 的表末）。

### 掃描用正則清單（全部 `re.IGNORECASE`）

版本比對在家族字與版本號之間用 `[\s-]*` 容忍空白或連字號；版本號後接 `(?![\d.])` 以免 `5` 誤吃 `5.5`。

| 家族 | 版本組合（標籤 → 正則） |
| --- | --- |
| Anthropic | `Claude Fable 5.1 Max`→`fable\s*5\.?1?\s*max`；`Fable 5.1`→`fable\s*5\.1\b`；`Fable 5`→`fable[\s-]*5(?!\.\d)`；`Mythos 5.1`→`mythos\s*5\.1`；`Opus 5.5`→`(?:claude\s*)?opus[\s-]*5\.5`；`Opus 5`→`opus[\s-]*5(?!\.\d)`；`Opus 4.8`→`opus[\s-]*4\.8`；`Sonnet 5.5`→`sonnet[\s-]*5\.5`；`Sonnet 5`→`sonnet[\s-]*5(?!\.\d)`；`Sonnet 4.6/4.5`→`sonnet[\s-]*4\.6` / `4\.5`；`Sonnet 4`→`sonnet[\s-]*4(?![\d.])`；`Haiku 3`→`haiku[\s-]*3` |
| OpenAI | `GPT-6 Astra`→`gpt[\s-]*6[\s-]*astra|astra[\s-]*6`；`GPT-6 Sol`→`gpt[\s-]*6[\s-]*sol`；`GPT-6 Luna`→`gpt[\s-]*6[\s-]*luna`；`GPT-6 Terra`→`gpt[\s-]*6[\s-]*terra`；`GPT-6`→`gpt[\s-]*6(?![\s-]?(astra|sol|luna|terra))`；`GPT-5.6 {Sol,Terra,Luna}`→`gpt[\s-]*5\.6[\s-]*(sol|terra|luna)`；`GPT-5.6`→`gpt[\s-]*5\.6`；`GPT-5.5 Pro`→`gpt[\s-]*5\.5[\s-]*pro`；`GPT-5.5`→`gpt[\s-]*5\.5`；`GPT-5`→`gpt[\s-]*5(?![\d.])` |
| Google | `Gemini 3.8 Flash`→`gemini[\s-]*3\.8`；`Gemini 3.7 Flash`→`gemini[\s-]*3\.7`；`Gemini 3.1 Pro`→`gemini[\s-]*3\.1`；`Gemini 3`→`gemini[\s-]*3(?![\d.])`；`Gemini 2.5 Pro`→`gemini[\s-]*2\.5` |
| DeepSeek | `V4.1 Pro`→`deepseek[\s-]*v?4\.1[\s-]*pro`；`V4.1 Flash`→`deepseek[\s-]*v?4\.1[\s-]*flash`；`V4.1`→`deepseek[\s-]*v?4\.1`；`V4 Pro/Flash/V4`→`deepseek[\s-]*v?4[\s-]*(pro|flash)?`；`V3.2`→`deepseek[\s-]*v?3\.2`；`V3.1`→`deepseek[\s-]*v?3\.1` |
| xAI | `Grok 4.8/4.7/4.6/4.5`→`grok[\s-]*4\.(8|7|6|5)`；`Grok 4`→`grok[\s-]*4(?![\d.])` |
| Z.AI | `GLM 5.5 Flash`→`glm[\s-]*5\.5[\s-]*flash`；`GLM 5.5`→`glm[\s-]*5\.5`；`GLM 5.3 Prime`→`glm[\s-]*5\.3[\s-]*prime`；`GLM 5.3 Flash/FlashX`→`glm[\s-]*5\.3[\s-]*flash`；`GLM 5.3`→`glm[\s-]*5\.3`；`GLM 5.2`→`glm[\s-]*5\.2` |
| Qwen | `Qwen3.8 Max Prime`→`qwen[\s-]*3\.8[\s-]*max[\s-]*prime`；`Qwen3.8 Max`→`qwen[\s-]*3\.8[\s-]*max`；`Qwen3.8 2.4T A95B`→`qwen[\s-]*3\.8[\s-]*2\.4t`；`Qwen3.8`→`qwen[\s-]*3\.8`；`Qwen3.7 Max`→`qwen[\s-]*3\.7[\s-]*max`；`Qwen3.7`→`qwen[\s-]*3\.7` |
| Moonshot | `Kimi K4`→`kimi[\s-]*k?4\b`；`Kimi K3`→`kimi[\s-]*k?3\b`；`Kimi K2.6`→`kimi[\s-]*k?2\.6` |
| 其他 | `Muse Spark 1.4`→`muse[\s-]*spark[\s-]*1\.4`；`MiMo v2.6 Pro`→`mimo[\s-]*v?2\.6`；`Nemotron`→`nemotron`；`MiniMax`→`minimax` |

> 注意：`GLM 5.3`、`Qwen3.8`、`Gemini 3`、`Grok 4` 等「世代」正則會**涵蓋**其後的變體（例：`GLM 5.3` 含 Prime／Flash），故表中兩列不可相加當獨立模型數。

---

## §2 X 池（55 筆）模型名出現統計表

**逐字統計（raw＝含第 31 筆；ex31＝排除第 31 筆）。** 第 31 筆（`@orihimexweb3`）是一則「The best ai models」排行榜清單貼文，一筆就點名約 20 個模型，是唯一會系統性膨脹所有低頻組合的雜訊源，故並列兩種數字。

| 模型（家族＋版本） | raw | ex31 | 首次出現列號（0-based） |
| --- | ---: | ---: | --- |
| Claude Sonnet 5.5 | 12 | 12 | 0,1,13,14,15,16,17,18,19,20,21,25 |
| GLM 5.3（含 Prime/Flash） | 11 | 10 | 31,45,46,47,48,49,50,51,52,53,54 |
| Grok 4.7 | 11 | 11 | 33,34,35,36,38,39,40,41,42,43,44 |
| Claude Opus 5.5 | 9 | 9 | 2,6,15,16,18,21,25,43,44 |
| GLM 5.3 Prime | 7 | 7 | 45,46,47,51,52,53,54 |
| Claude Sonnet 5 | 6 | 5 | 13,14,15,18,21,31 |
| Gemini 2.5 Pro | 6 | 6 | 6,7,8,9,10,11 |
| GPT-6 Sol | 5 | 5 | 2,19,25,26,27 |
| GPT-6 Astra | 5 | 4 | 16,22,31,43,44 |
| GPT-5.6 | 4 | 3 | 3,22,23,31 |
| DeepSeek V3.1 | 4 | 4 | 28,29,30,32 |
| Qwen3.8 Max | 4 | 3 | 31,48,49,50 |
| Claude Opus 5 | 3 | 2 | 0,22,31 |
| Kimi K3 | 3 | 2 | 22,30,31 |
| Claude Fable 5.1 | 3 | 2 | 31,43,44 |
| DeepSeek V4.1（Pro/Flash） | 3 | 3 | 45,48,50 |
| GLM 5.3 Flash/FlashX | 3 | 3 | 48,50,51 |
| GPT-5.5 | 2 | 1 | 25,31 |
| GPT-5 | 2 | 2 | 4,11 |
| GPT-5.6 Sol | 2 | 1 | 22,31 |
| Gemini 3.1 Pro | 2 | 1 | 22,31 |
| GLM 5.5 / GLM 5.5 Flash | 2 / 2 | 2 / 2 | 48,50 |
| Qwen3.8 Max Prime | 2 | 2 | 48,50 |
| Kimi K4 | 2 | 2 | 48,50 |
| Muse Spark 1.4 | 2 | 2 | 48,50 |
| DeepSeek V4.1 Pro | 2 | 2 | 48,50 |
| Claude Fable 5.1 Max | 2 | 2 | 43,44 |
| GPT-6（裸世代） | 2 | 2 | 43,44 |
| DeepSeek V4 / V4 Pro / V4 Flash | 1 / 1 / 1 | 0 | 31 |
| DeepSeek V3.2 | 1 | 0 | 31 |
| GPT-5.6 Terra / GPT-5.6 Luna | 1 / 1 | 0 / 1 | 31 / 23 |
| Gemini 3.8 Flash / 3.7 Flash | 1 / 1 | 0 / 0 | 31 |
| Gemini 3（裸世代） | 1 | 1 | 12 |
| Grok 4.6 / 4.5 | 1 / 1 | 0 / 0 | 31 |
| GLM 5.2 / Qwen3.7 Max / Kimi K2.6 | 1 / 1 / 1 | 0 | 31 |
| Claude Sonnet 4 | 1 | 1 | 11 |
| Claude Haiku 3 | 1 | 1 | 26 |
| MiMo v2.6 Pro | 1 | 1 | 45 |
| Qwen3.8 2.4T A95B | 1 | 0 | 31 |

### 清單外、但 X 池出現頻率高的模型（依 raw 排序）

| 模型 | raw | 現行清單有無 | OpenRouter id（格式猜測，2026-10 查得） |
| --- | ---: | --- | --- |
| Claude Opus 5.5 | 9 | ❌ 清單只有 Sonnet 4/5.5 | `anthropic/claude-opus-5.5` |
| Claude Sonnet 5 | 6 | ❌ 只有 5.5 | `anthropic/claude-sonnet-5` |
| GPT-6 Astra | 5 | ❌ 只有 Sol | `openai/gpt-6-astra` |
| GPT-5.6（Sol/Luna/Terra） | 4 | ❌ | `openai/gpt-5.6-luna`、`openai/gpt-5.6-terra`、`openai/gpt-5.6-sol` |
| Qwen3.8 Max | 4 | ❌ | `qwen/qwen3.8-max`（alias → `qwen/qwen3.8-max-0902`）|
| Claude Opus 5 | 3 | ❌ | `anthropic/claude-opus-5` |
| Kimi K3 | 3 | ❌ | `moonshotai/kimi-k3` |
| Claude Fable 5.1 | 3 | ❌ | `anthropic/claude-fable-5.1` |
| DeepSeek V4.1（Pro/Flash） | 3 | ❌ 只有 3.1 | `deepseek/deepseek-v4.1-flash`、`deepseek/deepseek-v4-pro-0813` |
| GLM 5.3 Flash/FlashX | 3 | ❌ 只有 Prime | `z-ai/glm-5.3-flash` |
| GLM 5.5（Flash） | 2 | ❌ | `z-ai/glm-5.5-flash`（未在 OpenRouter 首頁確認到，待複查） |
| Qwen3.8 Max Prime | 2 | ❌ | `qwen/qwen3.8-max-prime` |
| Kimi K4 | 2 | ❌（僅外洩名單，未見正式 id） | 未確認 |
| Muse Spark 1.4 | 2 | ❌ | `meta/muse-spark-1.4`（1.3 版為 `meta/muse-spark-1.3-contributor`）|
| Gemini 3.8 Flash | 1 | ❌ | `google/gemini-3.8-flash` |
| MiMo v2.6 Pro | 1 | ❌ | `xiaomi/mimo-v2.6-pro` |

### 現行 8 模型：X 池歸屬正確率（本節最關鍵）

檢查「被歸到某模型的 X 貼文，內文是否真的出現該模型自己的版本字」：

| 現行 modelId | X 筆數 | 內文真的有該版本字 | 判讀 |
| --- | ---: | ---: | --- |
| `anthropic/claude-sonnet-4` | 2 | **0 / 2** | 兩筆（列 0、1）都是日文速報，講的是 **Sonnet 5.5 上市**。完全張冠李戴。 |
| `openai/gpt-5` | 7 | **1 / 7** | 只有列 4「Either AGI or GPT-5」是真的；其餘談 GPT-5.6、GPT-6 Astra/Luna、GPT-6 Sol、印尼補習廣告。 |
| `anthropic/claude-sonnet-5.5` | 9 | 9 / 9 | 乾淨。 |
| `openai/gpt-6-sol` | 3 | 3 / 3 | 乾淨。 |
| `google/gemini-2.5-pro` | 7 | 6 / 7 | 幾乎全部真的在緬懷「2.5 Pro 是最好的一代」（列 6~11）；僅列 12 談 Gemini 3/3.1。 |
| `deepseek/deepseek-v3.1` | 5 | 4 / 5 | 列 30 只提 DeepSeek 品牌＋Kimi K3；其餘真的談 V3.1。 |
| `x-ai/grok-4.7` | 12 | 11 / 12 | 乾淨（列 37 只寫 Grok 4.6/4.7/4.8 世代）。 |
| `z-ai/glm-5.3-prime` | 10 | 7 / 10 | 列 48、49、50 其實談 GLM **5.5**／Qwen Prime 與外洩名單，被 Prime 模糊命中。 |

> **結論**：張冠李戴集中在 `Claude Sonnet 4` 與 `GPT-5` 兩席，與 owner 抽樣觀察一致。這兩席名下的貼文絕大多數在聊更新版本。

---

## §3 「品牌字無版本」無法歸屬量的統計

以 X 池 55 筆為母體：

- **完全沒有任何「家族＋版本」字樣**的貼文：**3 / 55（約 5.5%）**，列 5（印尼 turnitin 廣告）、24（「The most-used AI models are Chinese…」泛論）、37（「Grok 4.6/4.7/4.8 並行」世代泛論）。這些只能靠引擎 relevance 歸屬。
- **出現某家族品牌字、但該家族版本號未出現**的貼文（按家族，一筆可跨家族）：

| 家族 | 有品牌無版本的筆數 | 同家族有出現在幾筆 |
| --- | ---: | ---: |
| gpt / OpenAI | 2 | 15 |
| qwen | 2 | 4 |
| mistral | 2 | 2 |
| claude / Anthropic | 1 | 21 |
| grok | 1 | 13 |
| nemotron | 1 | 1 |
| llama | 1 | 1 |

**判讀**：X 池的「精確歸屬率」很高（52/55 至少有版本字，約 95%）；`mistral`、`nemotron`、`llama` 只以品牌或泛論出現（各 1~2 筆），**證據不足以入榜**。真正的問題不是「無法歸屬」，而是「舊版本查詢字命中新版本貼文」——屬歸屬規則過寬（見 §6），不是 alias 缺失。

> 補充風險：列 0、1 為日文、列 44 為韓文、列 29/48/50 為簡中，仍通過了 collect 的英文啟發式（`latin_ratio >= 0.6`），因內含大量拉丁字母（型號、URL）。這批多語貼文會拉高誤歸風險，值得在規則改版時一併處理。

---

## §4 引擎截斷問題的證據與網站呈現建議

### 機制（讀 vendor 引擎原始碼，pin commit `084662b`）

`vendor/last30days/lib/pipeline.py`：

```python
DEPTH_SETTINGS = {
    "quick":   {"per_stream_limit": 6,  "pool_limit": 15, "rerank_limit": 12},
    "default": {"per_stream_limit": 12, "pool_limit": 40, "rerank_limit": 40},
    "deep":    {"per_stream_limit": 20, "pool_limit": 60, "rerank_limit": 60},
}
MAX_SOURCE_FETCHES = {"x": 2, "jobs": 1, "linkedin": 1, ...}
```

- `collect.py` 跑的是 **default depth**（刻意不用 `--quick`，見 collect.py docstring：quick 會把每個 subquery 的來源上限壓到 2，X 會被擠掉）。
- `per_stream_limit`：每個 `(source, subquery)` 在進 pooling 前先截到 12 筆。
- `pool_limit` / `rerank_limit`：單次查詢的最終排序池上限 **40** 筆。
- `MAX_SOURCE_FETCHES["x"] = 2`：X 這種貴／易限流的來源，**單次查詢最多只 fan-out 2 個 subquery**（其餘來源較多）。X 池上限 ≈ 2 × 12 = 24 筆/查詢，再經融合、去重、歸屬、語言過濾後只剩更少。
- `planner.py` 的 `SOURCE_LIMITS` 在 quick 模式把所有意圖來源數壓到 2（`default` 不設限）——這是 collect 不用 quick 的原因。

### 這如何造成「各模型 20~35 筆趨於平均」

- 每個模型是**一次獨立查詢**，每次都被 `pool_limit=40` 封頂；8 模型全部落在 20~35 筆（reddit 82／hn 79／x 55），**沒有任何一個突破 40**。
- X 子集每個模型 2~12 筆，總 55 筆（平均 6.9）——同樣是 `per_stream_limit=12` × `MAX_SOURCE_FETCHES["x"]=2` 的天花板，不是「大家討論熱度一樣」。
- 引擎結果排序依據是**與查詢字串的 relevance**，不是社群 engagement 總量（只有 Reddit stream 有 `REDDIT_STREAM_KEEPERS=3` 的熱度保留位，X 沒有等價機制）。因此「聲量大的模型拿到較多筆」的關係被 cap 抹平。

### 「樣本數 ≠ 真實熱度」的直接證據

1. 引擎上限證據：`default` 的 `pool_limit=40` 與所有模型總數 20~35 完全吻合；`last30days-skill.md` 坑 3 亦記載「quick 每題 ~6 筆 Reddit、default 約 30–50、deep 70–100」的固定量級，並註明受 keyless 上限影響。
2. 外部熱度證據（僅作對照，不作為清單入選依據）：OpenRouter 2026-09 用量榜前列是 `z-ai/glm-5.3-flash`、`deepseek/deepseek-v4.1-flash`、`tencent/hy4-preview`、`openai/gpt-5.6-luna`（Teamday，2026-09），但這些在 X 池只有 2~4 筆；反觀舊的 `Gemini 2.5 Pro` 在 X 池有 6 筆（因為是「緬懷／對比」話題）。**樣本數反映的是「話題性與查詢字命中率」，不是使用量或人氣。**
3. 查詢字效應：清單用「顯示名」當 query（如 `Claude Sonnet 4`），引擎回傳的卻是當前熱門版本（Sonnet 5.5）——這既是 §2 誤歸的來源，也說明筆數受「查詢字與現況的落差」左右。

### 對網站（jason-lab）呈現的建議

- **不要把 `sampleSize` 當人氣／聲量呈現**。它是「本次抽樣中歸到該模型的貼文數」，受引擎上限支配。
- 每張卡／每列至少標示：`sampleSize`、`mentionsBySource`、`windowDays`、`updatedAt`、`confidence`（已是 Wilson 95% 下界）、以及 `kind: "community-sentiment"` 與 `disclaimer`（非 benchmark）。
- 樣本數 < 20 標「低樣本／僅供參考」（plan.md 既有規則）；各面向「有討論列數 < 10」標「樣本不足」，不得據以下結論（plan.md 裁定 8，progress-status 已列表）。
- 加「涵蓋來源：Reddit／HN／X」徽章，並明寫「近 30 天窗口偏袒新模型；X 僅涵蓋有 cookie 的抓取、且受引擎 per-source 上限影響」。
- 若要比「討論量」，需改用不經引擎截斷的獨立量測（如 OpenRouter token 用量或各來源 API 總數），**不可用本資料集的 `sampleSize` 代替**。
- 分數本身（態度聚合）仍可用，但請呈現為「在此抽樣中，社群對該模型的態度」，而非「該模型有多熱門」。

---

## §5 建議追蹤清單草稿（兩案並陳，供 owner 拍板）

### 分檔門檻（本案自訂，理由隨附）

以 **X 池內「家族＋版本」精確提及筆數（raw，含第 31 筆清單文）**為分檔依據；同時看 ex31 作穩健性：

- **A 檔（核心熱門，建議必追）**：X 池 ≥ 5 筆，或 ≥ 3 筆且 ex31 不縮水。
- **B 檔（邊緣／觀察）**：X 池 3~4 筆，但 ex31 掉到 < 3（即熱度主要來自單一清單文）。
- **C 檔（證據不足）**：X 池 < 3 筆。**依 owner 指示，C 檔不得拿 reddit/hn 數字補，標「證據不足」**。

> 門檻理由：X 池只有 55 筆，3 筆≈5% 已屬可見訊號；但單一清單文（第 31 筆）可一次灌多個模型，故設 ex31 為穩健性檢查。A 檔的「≥5」反映頭部討論；B 檔保留「可能有熱度但 X 池樣本不足以定論」的模型。

### 建議新增（依 X 池證據）

| 建議新增 modelId | X raw | ex31 | 檔位 | 證據（X 貼文主題） |
| --- | ---: | ---: | --- | --- |
| `anthropic/claude-opus-5.5` | 9 | 9 | **A** | 與 Sonnet 5.5 並列主要話題；Grok 4.7 對比、Terminal-Bench、Anthropic 旗艦。 |
| `anthropic/claude-sonnet-5` | 6 | 5 | **A** | Sonnet 5.5 的比較基準（「比 Sonnet 5 快 30%」）。 |
| `openai/gpt-6-astra` | 5 | 4 | **A** | 外洩名單、付費佔比、Grok 對比、GPT-6 世代。 |
| `z-ai/glm-5.3-flash` | 3 | 3 | **A（剛好過線）** | 外洩名單＋OpenRouter「Prime/Flash/FlashX」討論；外部用量榜第一（僅對照）。 |
| `deepseek/deepseek-v4.1-flash` | 3 | 3 | **A（剛好過線）** | 與 GLM 5.3 Prime 同場比較（列 45）＋外洩名單。 |
| `qwen/qwen3.8-max` | 4 | 3 | **B** | 外洩名單＋「Prime 變體」討論；列 31 清單文佔 1。 |
| `anthropic/claude-opus-5` | 3 | 2 | **B** | 付費佔比、日文速報、清單文。 |
| `moonshotai/kimi-k3` | 3 | 2 | **B** | 付費佔比、AWS Bedrock、清單文。 |
| `anthropic/claude-fable-5.1` | 3 | 2 | **B** | 賽博指數對比＋清單文。 |
| `openai/gpt-5.6-luna`（或整個 GPT-5.6 系列） | 4（系列） | 3 | **B** | 「使用量」話題（列 23）＋GPT-5.6 Sol 對比。 |
| `openai/gpt-6-luna` | 1 | 1 | **C** | 僅 OpenRouter 用量敘述，證據不足。 |
| `google/gemini-3.8-flash` | 1 | 0 | **C** | 僅清單文；X 池證據不足（雖然 9 月剛發布）。 |
| `google/gemini-3.1-pro` | 2 | 1 | **C** | 付費佔比＋清單文，證據薄。 |
| `xiaomi/mimo-v2.6-pro` | 1 | 1 | **C** | 僅一筆三方比較。 |
| `meta/muse-spark-1.4` | 2 | 2 | **C** | 僅外洩名單兩筆。 |
| `kimi-k4` | 2 | 2 | **C** | 僅外洩名單；尚無正式 id，暫不追。 |
| `nvidia/nemotron-*`、`minimax-*`、`mistral/*`、`meta/llama-*` | 0~1 | 0 | **C** | 只有品牌字／泛論，證據不足。 |

### 現行 8 模型的去留建議（兩案並陳）

| 現行模型 | X raw | 內文真為此版本 | 案一：保守（保留＋擴充） | 案二：汰換（移除舊世代） |
| --- | ---: | ---: | --- | --- |
| `anthropic/claude-sonnet-4` | 1 | 0/2 | **移除**（兩案皆同）——X 池 0 筆真的在講它，且已被 Sonnet 5/5.5 取代。 | **移除** |
| `anthropic/claude-sonnet-5.5` | 12 | 9/9 | **保留**（核心） | **保留**（核心） |
| `openai/gpt-5` | 2 | 1/7 | **移除**（或改名為 GPT-5.6/6 世代）——1/7 正確率是本池最差。 | **移除** |
| `openai/gpt-6-sol` | 5 | 3/3 | **保留** | **保留**（並可加 `gpt-6-astra`） |
| `google/gemini-2.5-pro` | 6 | 6/7 | **保留觀察**——X 池真的有一批「2.5 Pro 是最好一代」的討論，非誤歸。 | **移除或降級**——雖非誤歸，但屬舊世代；改追 `gemini-3.8-flash`（X 證據不足，需 owner 權衡）。 |
| `deepseek/deepseek-v3.1` | 4 | 4/5 | **保留觀察**——X 池確實有 V3.1 回顧貼文。 | **移除或改追 V4.1**——V3.1 已是 2025 舊世代，X 池亦有 V3.2/V4.1 話題。 |
| `x-ai/grok-4.7` | 11 | 11/12 | **保留**（核心） | **保留**（核心） |
| `z-ai/glm-5.3-prime` | 7 | 7/10 | **保留但考慮改名**——X 池有多筆在爭論「Prime 到底存不存在／有沒有覆蓋」，本質是 GLM 5.3 的變體。 | **改追 `glm-5.3` 或 `glm-5.3-flash`**（X 池 base GLM 5.3 raw 11 筆，比 Prime 更廣）。 |

**兩案差異一句話**：案一（保守）＝保留 Gemini 2.5 Pro 與 DeepSeek V3.1 當「舊世代對照」，只補新模型；案二（汰換）＝清單全面換成本月活躍世代，舊世代只留真正有 X 討論的。owner 需決定榜單定位是「現役模型比較」還是「含世代對照的長期追蹤」。

### 給 owner 拍板的點

1. 分檔門檻是否採「X 池 ≥3 筆精確提及」（本案用）？或更嚴（≥5）？
2. `Gemini 2.5 Pro`、`DeepSeek V3.1` 要「保留觀察」還是「汰換」？（它們非誤歸，是舊世代）
3. `GLM 5.3 Prime` 是否改追 base `GLM 5.3` 或 `GLM 5.3 Flash`？
4. X 池原本只有 55 筆，樣本量薄；是否要提高 X 抓取量（如 `--deep` 或調 `--max-per-source`／`--max-source-fetches`）以取得更可靠的清單依據？

---

## §6 給歸屬規則改版的輸入（alias map 需求）

以下家族有**暱稱／代號／變體後綴**，模糊比對時必須用 alias map 精確對應，否則會跨版本誤歸：

| 家族 | 暱稱／代號 | 對應正式模型 | 備註 |
| --- | --- | --- | --- |
| Anthropic | **Fable** | Claude Fable 5 / 5.1（Mythos-class 的公開版） | 2026-06-09 發布；別名不可只當獨立品牌。 |
| Anthropic | **Mythos** | Claude Mythos 5 / 5.1（受限版） | 與 Fable 同底層模型、不同防護。 |
| Anthropic | Prime 之外：`Sonnet`／`Opus`／`Haiku` 為等級詞 | 需與版本號綁定 | 只寫「Sonnet」無法歸屬（X 池 1 筆）。 |
| OpenAI | **Astra / Sol / Luna / Terra** | GPT-6 系列（以及 GPT-5.6 系列的 Sol/Luna/Terra） | 同一後綴在 GPT-5.6 與 GPT-6 都出現，**必須綁世代號**。 |
| Z.AI | **Prime / Flash / FlashX** | GLM 5.3 Prime / GLM 5.3 Flash | 「Prime」= 高速高價變體；X 池有「Prime 不存在」爭議。 |
| Qwen | **Max / Max Prime / 2.4T A95B** | Qwen3.8 Max / Max Prime | Max Prime 為高吞吐 SKU。 |
| Google | **Flash / Pro / TTS** | Gemini 3.8 Flash、3.1 Pro… | 「Flash」通用於多代。 |
| Moonshot | **K3 / K4 / K2.6** | Kimi K3 / K4 | K4 僅外洩名單。 |
| Meta | **Muse Spark** | Muse Spark 1.3/1.4 Contributor | |
| Xiaomi | **MiMo** | MiMo v2.6 Pro/Flash | |
| 隱形實驗室 | **Space Bunny Alpha**（匿名模型） | 無正式家族 | OpenRouter 上出現的 stealth 模型，名字像暱稱，勿誤歸。 |
| Z.AI | **Ox Alpha** | GLM-5.3-Flash 的代號 | 見 OfficeChai 報導。 |

**規則改版要點**：

1. **版本後綴白名單**：`Prime`、`Flash`、`FlashX`、`Pro`、`Max`、`Sol`、`Luna`、`Terra`、`Astra` 等只能附掛在對應世代後，不能單獨當模型名。
2. **世代綁定**：`GPT-6 Sol` ≠ `GPT-5.6 Sol`；alias 需帶世代號（`gpt-?6.*sol` vs `gpt-?5\.6.*sol`）。
3. **清單外黑名單**：`Fable`、`Mythos`、`Astra`、`Luna`、`Sol`、`Muse Spark`、`Space Bunny` 等若未納入清單，應進「其他已知模型」偵測集，命中時丟棄 query 的誤歸（目前 collect 的 `other_aliases` 只涵蓋清單內模型，清單外的會漏）。
4. **多語貼文**：日／韓／簡中貼文（列 0、1、44、29、48、50）通過英文啟發式；建議對 CJK 佔比過高者標記或另處理，避免誤歸。

---

## 來源（連結 + 查詢日期）

- 專案內：`data/evidence/2026-09-29.jsonl`（55 筆 X，2026-09-29 資料快照；本報告所有計數來源）。
- 專案內：`config/models.yaml`、`src/arena/collect.py`、`docs/plan.md`、`docs/progress-status.md`、`docs/research/last30days-skill.md`（2026-10-01 讀取）。
- 引擎原始碼：`vendor/last30days/lib/pipeline.py`（`DEPTH_SETTINGS`、`MAX_SOURCE_FETCHES`）、`vendor/last30days/lib/planner.py`（`SOURCE_LIMITS`）（2026-10-01 讀取，pin `084662b`）。
- OpenAI GPT-6 Astra 公告：<https://openai.com/index/gpt-6-astra/>（2026-10-01）
- OpenAI GPT-6 Sol/Luna：<https://openai.com/index/introducing-gpt-6-sol-and-luna/>（2026-10-01）
- Anthropic Claude Fable：<https://www.anthropic.com/claude/fable>；Claude Mythos：<https://en.wikipedia.org/wiki/Claude_Mythos>（2026-10-01）
- Anthropic Claude Opus 5.5：<https://www.anthropic.com/claude-opus-5-5>（2026-10-01）
- OpenRouter 模型頁（id 對照）：<https://openrouter.ai/models>；Qwen 3.8 說明：<https://openrouter.ai/blog/insights/qwen-3-8/>（2026-10-01）
- Qwen3.8 Max Prime id：<https://enterprisedna.co/directories/models/qwen-qwen3-8-max-prime/>（2026-10-01）
- Teamday OpenRouter 2026-09 用量榜：<https://www.teamday.ai/blog/top-ai-models-openrouter-2026>（2026-10-01；僅作熱度對照）
- 2026-09 發布總覽：<https://local-ai-zone.github.io/blog/September_2026_AI_Model_Updates.html>（2026-10-01）
- Mastra / Pi 模型目錄（id 交叉驗證）：<https://mastra.ai/models/gateways/openrouter>、<https://pi.dev/models>（2026-10-01）
