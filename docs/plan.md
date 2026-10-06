# llm-arena 資料契約與方法

> 本文件是 `llm-arena` 對外的**資料契約與方法說明**，自足：下游只要讀本文件與
> `data/scores.json`，就能正確讀取並呈現本專案的資料。若需要原始證據，再讀
> `data/evidence/*.jsonl`。
>
> 目前契約版本：`data/scores.json` 為 **schema v1.2**；`data/evidence/*.jsonl`
> 為 **v1.2／v1.3／v1.4**（v1.3 多一個可選 `thread` 欄位、v1.4 再為 `thread`
> 加一個可選 `body`；v1.2 形狀仍合法）。

## 1. 定位與產物

`llm-arena` 是 Jason Lab 的 LLM 社群評價**資料管線**：以 LLM 評審逐則判讀社群
（Reddit／Hacker News／X）對各模型的態度，再以可驗證的公式聚合成排行榜資料。
網站端（`jason-lab`）讀取本管線的資料產物來呈現排行榜。

- **這是社群聲量代理指標，不是 benchmark**：所有呈現都必須標明這點
  （`meta.kind` 鎖定 `"community-sentiment"`、`meta.disclaimer` 提供對外文字）。
- **分數由公式算出**，評審只逐則判讀態度，不直接給一個分數。
- 一筆資料＝**一則社群留言或一則推文**（不是一個討論串）；主貼本身不評分。

| 檔案 | 內容 |
| --- | --- |
| `data/scores.json` | 算好的分數（網站唯一需要的輸入） |
| `data/evidence/*.jsonl` | 逐則留言／推文與評審判定，讓每個分數可回溯 |
| `data/evidence/archive/` | 舊池（粒度為「一個討論串」），留作稽核，**不入聚合** |
| `data/models.json` | 模型清單與 OpenRouter 定價／context（`build` 附掛定價用） |

## 2. 管線概觀

```
fetch-models → collect → score → build → validate
```

- `fetch-models`：讀人工清單 `config/models.yaml`，附掛 OpenRouter 公開 API
  `https://openrouter.ai/api/v1/models` 的定價與 context length（只用 API，不爬 HTML），
  寫出 `data/models.json`。OpenRouter 掛掉時不影響人工清單（缺欄填 `null`）。
- `collect`：以 `last30days` 引擎抓近 30 天 Reddit／Hacker News／X 討論，落地成
  `data/evidence/YYYY-MM-DD.jsonl`（UTC 日期），並做歸屬判定、去重與原子寫入。
- `score`：LLM 評審對逐則資料一次回答六題，回填 `votes`／`juryVotes`／`judge`。
- `build`：由 evidence 聚合出 `data/scores.json`（分數全部由公式算出）。
- `validate`：檢查資料是否符合 schema；不合法時以非 0 結束碼收場。

## 3. `data/scores.json`（schema v1.2）

```jsonc
{
  "meta": { /* 見 3.1 */ },
  "models": [ /* 見 3.2 */ ]
}
```

### 3.1 `meta`

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `schemaVersion` | number | 契約版本，現為 **`1.2`** |
| `generatedAt` | string | 產出時間（ISO 8601） |
| `windowDays` | int ≥ 1 | 取樣窗口天數（現為 `30`） |
| `kind` | string | 固定 `"community-sentiment"`（明確標示不是 benchmark） |
| `disclaimer` | string | 對外顯示的免責聲明 |
| `judge` | object | 評審資訊，見下 |
| `dimensions` | array | `[{ "id": "quality", "label": "智能" }, …]`；**站方表格欄位由它驅動**，順序即欄位順序 |
| `weights` | object | 面向 id → 總分權重（0～1） |
| `sourcesCovered` | array | 本檔涵蓋的來源（如 `reddit`／`hn`／`x`），供涵蓋徽章 |
| `notes` | string | 補充說明（窗口偏誤；若樣本數 0 的模型被排除，於此交代清單） |

`meta.judge`（v1.2）：

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `kind` | string | 固定 `"llm-jury"` |
| `members` | array | 評審成員模型 id（**現為單一成員 `qwen/qwen3.7-flash`**） |
| `calibrated` | bool | 是否已通過校準驗證（gold 考卷達標），現為 `true` |

現行 `meta.dimensions` 為五個面向：

| id | label |
| --- | --- |
| `quality` | 智能 |
| `speed` | 速度 |
| `tokenEfficiency` | Token 效率 |
| `tokenUsage` | Token 用量 |
| `priceValue` | CP 值 |

現行 `meta.weights` 為 `quality` 0.5、`speed` 0.2、`priceValue` 0.2、
`tokenEfficiency` 0.05、`tokenUsage` 0.05。

### 3.2 `models[]`

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `id` | string | 模型識別碼，對應 evidence 的 `modelId` |
| `name` | string | 顯示名稱 |
| `provider` | string | 廠牌（供網站篩選） |
| `score` | number 0～100 | 總分（`weights` 加權，null 面向剔除後重歸一） |
| `dimensions` | object | 面向 id → 分數（0～100）或 **`null`**；**鍵必須恰好等於 `meta.dimensions` 的 id 集合** |
| `priceUsdPerMTok` | object / null | `{ "in": …, "out": … }` 每百萬 token 美元定價；硬資料、非態度；查無為 `null` |
| `dimensionSamples` | object | 面向 id → 非負整數（該面向「有表態」樣本數）；另含 `overall` 鍵 |
| `sampleSize` | int ≥ 0 | 該模型**可聚合**的 evidence 筆數（六題投票完整且為現任評審的列；未評分／不完整列不計） |
| `positiveRate` | number 0～1 | **總評**正面率；分母為「有表態」筆數（見 §5） |
| `confidence` | number 0～1 | 打過折的正面率（Wilson 95% 下界，見 §5） |
| `mentionsBySource` | object | 來源 → 可聚合筆數（與 `sampleSize` 同口徑） |
| `evidence` | array | 指向 evidence 的參照清單，格式見下；**含該模型全部列（含未評分者）** |
| `updatedAt` | string | 此列的更新時間（ISO 8601） |

`evidence` 參照格式：`[目錄/]檔名.jsonl#l<行號>`，目錄前綴可省略。
例：`evidence/2026-10-01.jsonl#l1204`。

### 3.3 讀取規則（下游必守）

- `dimensions` 某一面向為 **`null`**＝**「資料不足」**，站方必須顯示為資料不足，
  **不得顯示成 50**。`dimensionSamples` 對應為 0 也代表該面向沒有正負表態。
- 分數集中、樣本量落差大：呈現務必帶 **`sampleSize`** 與 **`confidence`**，
  並把「樣本不足」的面向照實標示。
- `sampleSize = 0` 的模型**不會出現**在 `models[]`，而是列在 `meta.notes`。
- `positiveRate` 是「**有表態者中**」的正面比例，不是「所有人中喜歡的比例」；
  呈現時務必說明（見 §9）。

## 4. `data/evidence/*.jsonl`（v1.2／v1.3／v1.4）

每行一筆 JSON。v1.3 相對 v1.2 多一個**可選** `thread` 欄位；v1.4 再為 `thread`
加一個**可選** `body`（主貼內文）。`validate` 同時接受三種列。

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `hash` | string | 去重鍵：正規化文字（小寫、空白壓扁）的 sha256，**跨所有 evidence 檔去重** |
| `modelId` | string | 對應 `scores.json` 的模型 id |
| `source` | string | 來源：`reddit`／`hn`／`x`（開放字串集合） |
| `url` | string | 原文永久連結（可連回逐則留言／推文） |
| `author` | string / null | 原作者；補不到時為 `null`（站方顯示「未知作者」） |
| `postedAt` | string | 張貼時間（ISO 8601） |
| `text` | string | 內容；一律**截斷至 1200 字元** |
| `thread` | object / null | **v1.3／v1.4 可選**：留言所屬主貼與歸屬依據，見下；X 推文與 v1.2 舊列不帶此欄 |
| `votes` | object / null | 六題聚合票（`overall` ＋五面向），見下；未評分時為 `null` |
| `juryVotes` | object / null | 逐位評審的原始票（`<面向>.<評審短名>` → 標籤或 `null`） |
| `judge` | string / null | 評審與版本，格式 `llm-jury@<membersHash 前 8 碼>`；未評分為 `null` |

`thread`（v1.3／v1.4）：

```jsonc
"thread": {
  "url": "<主貼永久連結>",
  "title": "<主貼標題>",
  "modelId": "<該串歸屬的模型>",
  "body": "<主貼內文；v1.4 可選，截斷至 1200 字元>"
}
```

`thread.modelId` 一律是**該串**（主貼）的歸屬模型，不一定等於該列的 `modelId`
（留言若自己精確提到另一個清單模型，可改判，見 §7）。

`thread.body`（v1.4）是**可選**欄位：當主貼**標題不帶版本號**、版本號只出現在
**內文**時，`title` 單獨撐不起歸屬憑據，`body` 補上內文讓歸屬可回溯。主貼標題
已帶版本號、或主貼無內文（純連結／圖片）時省略。截斷規則與 `text` 相同（1200
字元）；`body` **不影響**去重鍵 `hash`（`hash` 一律以 `text` 計算）。

`votes` 的六題與標籤：

| 題 id | 問的是 | 標籤 |
| --- | --- | --- |
| `overall` | 作者對該模型的**總評**態度 | `positive`／`negative`／`neutral` |
| `quality` | 能力與輸出品質（正確性、聰明度、可靠性） | `positive`／`negative`／`not-discussed` |
| `speed` | 回應速度／延遲／吞吐 | `positive`／`negative`／`not-discussed` |
| `tokenEfficiency` | 囉嗦度與上下文／token 利用效率 | `positive`／`negative`／`not-discussed` |
| `tokenUsage` | 完成任務所需的 token 量／額度消耗 | `positive`／`negative`／`not-discussed` |
| `priceValue` | 價格與性價比 | `positive`／`negative`／`not-discussed` |

每題為 `{ "label": …, "prob": … }`：

- **現行為單一評審，`prob` 恆為 `1.0`**。
- 若未來擴編為多評審：`label` 為多數決結果、`prob`＝同票比例；票數相同的面向
  `label` 與 `prob` 皆為 `null`（視同資料不足，`build` 自動排除）。
- `not-discussed`＝「未談該面向，或談了但沒有評價立場」；**不同於**總評的
  `neutral`（談了但中立）。`neutral` 只屬於 `overall`，`not-discussed` 只用於面向。

## 5. 聚合公式

`build` 只計**已評分**的列（`judge` 為現任評審、`votes` 六鍵完整）。對每個模型、
每個面向：

- `P`＝positive 數、`N`＝negative 數、`n = P + N`（`not-discussed` 不計入）。
- `n = 0` → 該面向為 **`null`**（「資料不足」，不得當成 50）。
- `raw = (P − N) / n`
- **K=10 收縮**：`dimScore = 50 × (raw + 1) × n / (n + K) + 50 × K / (n + K)`，
  其中 `K = 10` 為偽樣本數。樣本越小越往 50 靠攏（`n=10` 收一半、`n=90` 收 10%），
  四捨五入到小數第一位。例：`n=10` 全正 → `75.0`。

**總分** `score` ＝非 null 面向的加權平均（權重讀 `meta.weights`，剔除 null 後
**重歸一**），以四捨五入後的面向分數計算，讓榜上數字可手算回推。

**總評正面率與信心值**（以 overall 為準）：

- `positiveRate = P / (P + N)`：分母是**「有表態」的筆數**（正面＋負面）。
  總評為 `neutral` 的留言（離題、純語助詞、問問題等）**不進分母**。
- `confidence` ＝該正面率的 **Wilson 95% 下界**（`z = 1.96`）。
- 分母就是 `dimensionSamples.overall`（有表態筆數）。站方可呈現
  「N 則留言中 M 則有表態」。若 `P + N = 0`（全部 neutral）：
  `positiveRate = 0.0`、`confidence = 0.0`、`dimensionSamples.overall = 0`，
  站方應以「樣本不足」呈現，**不得**解讀為「全數不滿」。
- `sampleSize` ＝**可聚合**列數（六題投票完整且為現任評審）；`evidence` 參照清單
  則含該模型**全部**列（含未評分者），兩者可能不同。五個面向不受此規則影響。

## 6. 評審契約

- **評審**：LLM 單一評審 **`qwen/qwen3.7-flash`**（經 OpenRouter 呼叫）。
  對每則資料**獨立呼叫一次**、同 prompt、同 rubric、**溫度 0**、JSON 輸出，
  一次回答六題（overall ＋五面向）。
- **judge 識別**：`llm-jury@<membersHash 前 8 碼>`；`membersHash` 為評審成員 id
  排序後以換行串接的 sha256。現行值為 **`llm-jury@557e1059`**。
- **校準**：評審在 gold v2 考卷上 overall accuracy **0.8174**（門檻 0.80），
  owner 認可後 `meta.judge.calibrated` 為 `true`。gold 由多個 LLM 逐則標註、
  以多數決定案；詳見 `docs/calibration-report.md`。
- **多數決機制保留在程式中**：未來要擴編為多評審，只需改評審成員清單
  （`arena.jury.JURY_MEMBERS`）；單一成員時 `prob` 恆為 `1.0`、無平手。
  歷史上的初版評審器（JEV 家族小模型）已淘汰，本節不再贅述。
- **金鑰解析順序（dotenv 鏈）**：行程環境變數（`OPENROUTER_API_KEY` 或別名
  `OPENROUTER_KEY`）→ 專案自己的 `.env`（已 gitignore，`ARENA_DOTENV` 可覆寫）
  → 中央金鑰檔（預設 `~/.keys/.env`，可由環境變數或 `.env` 內的 `ARENA_ENV_FILE`
  指定）。三者皆缺時明確報錯，**不靜默降級**。
- **呼叫模式與成本**：預設同步呼叫；`--batch` 可切 batch API（半價、非同步）。
  單一評審成本約**每千則 $0.04**（原四人評審團約 1/16 之譜）。

## 7. 模型清單與歸屬規則

### 7.1 模型清單維護

- 清單以**人工維護**的 `config/models.yaml` 為**主**（決定要追哪些模型）；
  OpenRouter 只負責附掛定價與 context length，不決定清單內容。
- 清單 v2（15 席）＝沿用 5 席＋新增 A 檔 5 席＋B 檔 5 席。2026-10-01 換血時移除
  了舊世代且被引擎模糊比對嚴重污染的模型（`claude-sonnet-4`、`gpt-5`、
  `deepseek-v3.1`），保留 `gemini-2.5-pro` 等。入選以 X 池實掃證據為準
  （版本精確提及的筆數），查無 OpenRouter id 者標缺欄。
- 清單需定期擴充：新模型的討論在過嚴的歸屬規則下會全被丟棄，直到它被納入清單。

### 7.2 歸屬規則（一則留言算哪個模型的證據）

採**兩層判定**：

- **串層級（主貼定歸屬）**：主貼 `title` ＋ `body` 必須**精確提及**清單內某版本
  才通過。只提品牌字無版本號 → 丟；提到「家族＋版本」但版本不在清單 → 丟
  （misattributed）。暱稱與變體後綴**必須綁定世代**（例如 `GPT-6 Sol` 與
  `GPT-5.6 Sol` 不同）；該世代在清單裡獨佔一席時，社群只寫世代也算命中。
  未通過歸屬的串，其所有留言皆丟。
- **留言層級（歸屬與情緒分離）**：主貼決定**整串**的模型，留言**繼承該串**——
  因為留言本來就不會重複寫出模型版本（「它好爛」「這代超強」）。留言自己精確
  提到清單內某版本時歸那個（可改判）；提到清單外版本／他家族品牌字 → 丟。
  每串留言上限 20 則，Reddit 依熱度（score）、Hacker News 依樹狀順序取。
- **可稽核性**：每則留言列以 `thread = {url, title, modelId, body?}` 記錄歸屬依據，
  能分辨「這則自己提到模型」或「繼承主貼」；`body`（v1.4，可選）是主貼內文，
  當標題不帶版本號時才是可佐證的憑據；X 推文不帶此欄。

## 8. schema 版本歷史

| 版本 | 日期 | 重點 |
| --- | --- | --- |
| **v1.1** | 2026-09-29 | 維度從固定欄位改為**開放 map**（5 面向＋總評），網站表格欄位由 `meta.dimensions` 驅動；evidence 的單筆 `label`／`prob` 改為 `votes` map；區分 `not-discussed`（沒談）與 `neutral`（談了但中立）；`P+N=0` 的面向為 `null`（資料不足）；定價 `priceUsdPerMTok` 移到 model 層級；新增 `meta.dimensions`／`weights`／`sourcesCovered`；`meta.judge = {model, revision, calibrated}`。 |
| **v1.2** | 2026-09-30 | 引入 LLM 評審團：evidence 新增 `juryVotes`（逐位評審的原始票）；`votes` 改為多數決聚合，平手時 `label`／`prob` 可同為 `null`；`judge` 格式改為 `llm-jury@<hash 8 碼>`；`meta.judge = {kind: "llm-jury", members, calibrated}`、`meta.schemaVersion = 1.2`。**現行版本。** |
| **v1.3** | 2026-10-02 | evidence 新增**可選** `thread` 欄位（`{url, title, modelId}`）記錄歸屬依據；`validate` 同時接受 v1.2（無 `thread`）與 v1.3（有 `thread`）。**`scores.json` 契約不變，仍為 v1.2。** |
| **v1.4** | 2026-10-05 | `thread` 新增**可選** `body`（主貼內文，截斷至 1200 字元），補足「標題不帶版本號、版本只在內文」的歸屬憑據；`validate` 同時接受 v1.2／v1.3／v1.4。X 推文列仍**不得**帶 `thread`（含 `body`）；`body` 不影響 `hash`。**`scores.json` 契約不變，仍為 v1.2。** |

補充（語意變更，版本號不變）：2026-10-02 起，`positiveRate` 與 `confidence` 的
分母明確改為「**有表態**」筆數（`neutral` 不計），並以 `dimensionSamples.overall`
揭露該數。欄位未增減，故 `schemaVersion` 維持 `1.2`；但這是**語意變更**，
下游文案必須同步（正面率＝有表態者中的比例）。

## 9. 呈現注意事項

- 一律標明「**社群聲量代理指標，非 benchmark**」。
- 近 30 天窗口＝**近期聲量**，會偏袒剛發布／剛洗版的模型；輸出必須標示。
- **樣本數不等於人氣**：搜尋引擎每次查詢有回傳上限，各模型筆數趨於平均是截斷
  造成的假象；不要把 `sampleSize` 當成熱門度條。
- **正面率是「有表態者中的比例」**：留言近半數是離題／無立場（`neutral`），
  那些不進分母；呈現時要說明，否則使用者會把 0.5 誤讀成「一半的人沒意見」。
- **歸屬可能繼承主貼**：多數留言本身沒寫模型名，是依主貼標題／內文歸屬；呈現
  逐則引用時建議一併顯示主貼標題（`thread.title`）與連結，標題不帶版本號時
  （`thread.body` 存在）一併顯示內文，讓查核者知道上下文。
- K=10 收縮使小樣本分數往 50 靠攏；低樣本模型的排名是小樣本效應，務必帶
  樣本數與 `confidence`。面向「有表態」筆數 < 10 時標『樣本不足』，不得據以結論。
