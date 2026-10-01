# llm-arena

**Jason Lab** 的第一個工具：LLM 社群評價排行榜的**資料管線**。

這個 repo 只負責「產生可驗證的社群評價資料」，不負責網站外觀。
網站（[`jason-lab`](../jason-lab)）讀取本 repo 的資料產物來呈現排行榜。

- 定位：真的能跑、能重跑的評測工具，而不是展示品
- 狀態：**v1.3 資料管線運作中**——CLI 五個子命令（`fetch-models`／`collect`／`score`／
  `build`／`validate`）皆已實作；C5 校準驗證已通過（gold v2、overall 0.8174 過關，
  owner 認可 2026-09-30，`meta.judge.calibrated: true`）。
  2026-10-01 完成 C9：清單 v2（15 席）＋ Reddit／HN 留言逐則＋歸屬改版本精確比對，
  新池 `data/evidence/2026-10-01.jsonl` 已產（126 筆，全部留言級／推文級且 url 可連回）。
  2026-10-02 以 `qwen3.7-flash` 單評審重評並產出 **v2 榜單**（15 席，網站即讀此檔）。
  詳見 `docs/plan.md` 與 `docs/calibration-report.md`

## 產出什麼

| 檔案 | 內容 |
| --- | --- |
| `data/scores.json` | 算好的分數（網站唯一需要的輸入） |
| `data/evidence/*.jsonl` | 原始**留言／推文**與引用，讓每個分數都可回溯審核 |
| `data/evidence/archive/` | 舊池（2026-09-29，粒度為「一個討論串」）留作稽核對照，不入聚合 |

## 方法（概要）

1. **模型清單（v2，15 席）**：以人工維護清單為主，附掛 OpenRouter 公開 API `https://openrouter.ai/api/v1/models` 的定價與 context length（用 API，不爬 HTML）。
   清單 2026-10-01 換血：移除 `claude-sonnet-4`／`gpt-5`／`deepseek-v3.1`
   （舊世代且被引擎模糊比對嚴重污染，X 池實測 Sonnet 4 命中 0/2、GPT-5 命中 1/7），
   保留 `gemini-2.5-pro` 等 5 席，新增研究報告的 A 檔 5 席＋B 檔 5 席
   （`docs/research/model-roster-survey.md`，契約見 `docs/plan.md` 裁定 14）。
2. **社群收集**：排程 agent 使用 `last30days` 技能抓近 30 天社群討論（Reddit／HN／X）。
   Reddit／HN 改「**留言逐則**」：主貼不評分，每個討論串取熱門前 10 則**留言**，
   每則留言各自成一筆 evidence（裁定 13）；X 維持每則推文一筆。
   歸屬規則已收緊為**版本精確比對**（裁定 14）：只提品牌字無版本號 → 丟；
   提到「家族＋版本」但該版本不在清單 → 丟（misattributed）；暱稱必綁世代
   （`GPT-6 Sol` ≠ `GPT-5.6 Sol`，`GLM 5.3 Prime` ≠ `GLM 5.3 Flash`）。
3. **評分（LLM 單一評審）**：`qwen3.7-flash`（經 OpenRouter）對逐則貼文**一次**回答
   六題（overall＋五面向、溫度 0、JSON 輸出）。
   歷史：初版為四人評審團多數決，2026-10-01 owner 裁定收斂為單一評審——
   qwen3.7-flash 在 gold v2 上單飛 0.852（並列第一、過 0.80 門檻），成本降為 1/16。
   多數決機制保留在程式中（`arena.jury.JURY_MEMBERS` 改一行即可擴編）。

   > 初版評分器 `laya`（JEV 家族小模型）已於 2026-09-30 淘汰：它在 gold 考卷上
   > 只有 0.4424，對這種語意判斷明顯不準確（domain fit 問題）。研究與淘汰理由見
   > `docs/research/laya-usage-accuracy.md`；其 0.4424 量自已作廢的舊 gold，
   > 與現行評審團的 0.8174 沒有直接對比。
4. **分數是算出來的**：每個面向 `raw=(P−N)/(P+N)`、`dimScore=50×(raw+1)`，
   再以偽樣本數 `K=10` 向 50 收縮（樣本越小越往 50 靠攏）；總分＝各面向加權平均
   （權重見 `meta.weights`，null 維度剔除後重歸一）。公式可驗證，模型不直接打分。

> 這是**社群聲量代理指標，不是 benchmark**。所有呈現都必須標明這點。

## 上線門檻（2026-09-30 達成、2026-10-01 裁定修正）

- [x] ground truth（gold v2）：四家真 LLM 逐則 API 標註、≥3/4 多數定案 117 列；
      評審團 vs gold：overall **0.8174** 過關（門檻 0.80），報告見
      `docs/calibration-report.md`
- [x] 去重機制（正規化 hash，跨檔與跨來源轉貼只算一次）
- [x] 偏袒防護：評審團成員刻意避開 gold 標註的模型家族；「社群聲量代理指標、
      非 benchmark」的定位以 `meta.disclaimer` 全程標示。（原構想的「送評前遮蔽
      模型名稱」未實作——貼文文字天然含模型名，改倚賴多數決與上述定位標示）
- [x] 面向驗收門檻（owner 裁定 2026-10-01）：五面向改比「accuracy 勝過常數
      not-discussed baseline」（not-discussed 佔九成時絕對 0.80 是誤導性指標）；
      有討論列數 <10 的面向標『樣本不足』，站方呈現須標註各面向可信度。

## 資料現況（2026-10-02，v2 榜單已產出）

- `data/models.json`：**15 席**，OpenRouter 實查全部有定價與 context（0 缺欄）。
- `data/evidence/2026-10-01.jsonl`：**126 筆**（reddit 54／x 50／hn 23），
  每筆的 url 都可連回、text 都精確提及該 row 的模型版本
  （`.venv/bin/python tools/verify_pool.py data/evidence/2026-10-01.jsonl` 可複驗）。
- `data/scores.json`：**v2 榜單已產出**（2026-10-02；15 席、judge=`llm-jury@557e1059`、
  `sourcesCovered=[hn,reddit,x]`）。一筆＝一則留言、樣本小（2~25）＋K=10 收縮，
  分數集中 43~60、`confidence` 低，呈現須帶樣本數與可信度；Gemini 2.5 Pro 第 2 名
  是緬懷文小樣本效應。重跑指令：`arena score` → `arena build` → `arena validate`；
  key 來源見下（dotenv 鏈，本專案 `.env` 已指向中央金鑰檔，已 gitignore）。

## 目錄結構

```
src/               fetch-models / collect / score / build / validate（＋calibrate 標註工具）
data/              scores.json、evidence/*.jsonl、calibration/（C5 標註工作檔）
tools/             verify_pool.py（池品質驗收）、gold 標註與驗證工具
tests/
docs/              plan.md、annotation-guide.md、research/
.env.example       環境設定範例（複製為 .env；.env 已 gitignore）
```

## CLI

```bash
arena fetch-models   # 更新模型清單與定價
arena collect        # 抓取社群貼文（排程執行）
arena score          # LLM 評審（qwen3.7-flash）逐則評分
arena build          # 產出 data/scores.json
arena validate       # 檢查資料是否符合 schema
```

## 開發

需求：Python 3.10+（專案用 `uv` 管理虛擬環境，沒有 `uv` 就用 `python3 -m venv`）。

```bash
# 1. 建立虛擬環境
uv venv .venv                 # 或：python3 -m venv .venv

# 2. 以可編輯模式安裝（含開發相依：pytest）
uv pip install --python .venv/bin/python -e ".[dev]"
# 沒有 uv 時：.venv/bin/pip install -e ".[dev]"

# 3. 執行 CLI
.venv/bin/arena --help
.venv/bin/arena fetch-models  # 合併人工清單與 OpenRouter，寫入 data/models.json
.venv/bin/arena build         # 由 evidence 聚合出 data/scores.json（會自動跑 validate）

# 4. 跑測試
.venv/bin/python -m pytest
```

### 評分相依（`arena score`，LLM 單一評審）

評分走 OpenRouter API，需要 OpenRouter API key；**缺 key 時明確報錯，不會靜默降級**。
金鑰來源依序（dotenv 鏈，2026-10-02）：

1. 行程環境變數 `OPENROUTER_API_KEY`（或別名 `OPENROUTER_KEY`）
2. **專案自己的 `.env`**（`<repo>/.env`，已 gitignore；`ARENA_DOTENV` 可覆寫）
3. **中央金鑰檔**（預設 `~/.keys/.env`；由環境變數或 `.env` 內的 `ARENA_ENV_FILE` 指定）

一份 key 要給多個程式共用時，建議把 key 放中央金鑰檔，各專案 `.env` 只寫
`ARENA_ENV_FILE=~/.keys/.env`（設定範例見 `.env.example`）：

```bash
cp .env.example .env            # 方式 A：直接在 .env 寫 OPENROUTER_API_KEY=...
                                # 方式 B：.env 只寫 ARENA_ENV_FILE=~/.keys/.env
```

預設為同步呼叫（溫度 0）；`--batch` 可切 batch API（半價、非同步，
批次要等數分鐘起跳），`ARENA_SCORE_NO_BATCH=1` 可強制同步。

```bash
# 對預設路徑 data/evidence/*.jsonl 逐則評分
.venv/bin/arena score

# 指定單一檔（ARENA_EVIDENCE_FILES 以 : 分隔多個路徑）
ARENA_EVIDENCE_FILES=data/evidence/2026-10-01.jsonl .venv/bin/arena score

# 重評所有行，包含已有 votes 的行（預設會跳過）
.venv/bin/arena score --force
```

評分結果把 `votes`（六題標籤）、`juryVotes`（評審的原始票，現為單一評審）與
`judge`（`llm-jury@<membersHash 前 8 碼>`，現為 `llm-jury@557e1059`）回填進
evidence。輸出採**原子寫入**（先寫同目錄暫存檔再 rename），中途失敗不會留下
半截 jsonl；已有 `votes` 的行會跳過，因此可重複執行。單一評審成本約
**每千則 $0.04**（126 則 × 6 題約 $0.005；原四人多數決為 $0.13）。
評審名單與契約見 `docs/plan.md` 實作裁定 12。

**完整重跑**（清單與歸屬規則變更後，2026-10-02 實測）：

```bash
.venv/bin/arena fetch-models                  # 清單 v2 → data/models.json
.venv/bin/arena collect                       # 新池（慢，實測約 24 分鐘，建議丟背景）
.venv/bin/arena score                         # 逐則評分（需 key）
.venv/bin/arena build                         # 產出 data/scores.json（自動 validate）
.venv/bin/arena validate data/scores.json data/evidence/2026-10-01.jsonl
```

> 舊評分器 `laya`（JEV 家族、CPU 本地推論）的安裝與調校說明已隨其淘汰移除；
> 歷史選型理由與坑清單保留在 `docs/research/jev-scoring.md` 與
> `docs/research/laya-usage-accuracy.md`。

### 資料契約（schema v1.2）

evidence 的每則貼文以 `votes` 記錄評審的**判定結果**（六題：`overall` 總評＋
五個面向 `quality`／`speed`／`tokenEfficiency`／`tokenUsage`／`priceValue`），
每題 `{label, prob}`。**現行為單一評審，`prob` 恆為 `1.0`**；若未來擴編為多評審，
`prob`＝同票比例、票數相同（平手）的面向 `label`／`prob` 為 `null`（視同資料不足，
build 自動排除）。評審的原始票保留在 `juryVotes.<面向>.<評審短名>`。未評分時
`votes`／`juryVotes`／`judge` 為 `null`，結構仍合法。

rubric（題目文字見 `src/arena/score.py` 的 `QUESTION`；`overall` 用 positive／negative／
neutral，五個面向用 positive／negative／`not-discussed`）：

| 題 id | 問的是 | 五面向的第三個標籤 |
| --- | --- | --- |
| `overall` | 作者對該模型的**總評**態度 | （用 neutral） |
| `quality` | 模型的**能力與輸出品質**（正確性、聰明度、可靠性） | `not-discussed` |
| `speed` | 模型的**回應速度／延遲／吞吐** | `not-discussed` |
| `tokenEfficiency` | 模型的**囉嗦度與上下文／token 利用效率** | `not-discussed` |
| `tokenUsage` | 完成任務**所需的 token 量／額度消耗** | `not-discussed` |
| `priceValue` | 模型的**價格與性價比**（定價、訂閱、免費額度 CP 值） | `not-discussed` |

`not-discussed`＝「貼文未談該面向，或談了但沒有評價立場」，**不同於**「談了但中立」
（`neutral` 只屬於 `overall`）。

`data/scores.json`（v1.2）：`meta.dimensions` 宣告站方表格欄位（id／label），
`models[].dimensions` 是開放 map，**鍵必須恰好等於 `meta.dimensions` 的 id 集合**
（`validate` 會交叉檢查）。某一面向完全沒有正負表態時，該維度是 **`null`**＝
**「資料不足」**，站方必須顯示為資料不足，**不得顯示成 50**。`meta.weights` 是總分權重，
`priceUsdPerMTok` 在 model 層級（查無定價為 `null`），另有 `dimensionSamples` 記錄各面向樣本數。

也可以不啟用虛擬環境，直接用 `python -m arena` 執行（需先安裝專案）。

五個子命令（`fetch-models`／`collect`／`score`／`build`／`validate`）都已實作；
不合法的資料一律以非 0 結束碼回報，不會靜默成功。

### fetch-models

- 人工清單在 `config/models.yaml`（**主**，決定要追哪些模型）；定價與 context
  length 由 `https://openrouter.ai/api/v1/models`（免 key、**只用 API 不爬 HTML**）
  附掛到人工清單上。輸出 `data/models.json` 供 `build` 使用。
- OpenRouter 掛掉（斷網／非 200／逾時）時**不影響人工清單**：缺的欄位放 `null`
  並列在該筆的 `missing`，`meta.openrouterStatus` 記為 `unavailable`，退出碼仍為
  `0`（只在 stderr 說明）。
- `arena fetch-models` 的預設路徑是 `config/models.yaml` → `data/models.json`；
  程式呼叫 `arena.fetch_models.run(args)` 時可用 `args.config`／`args.output`
  覆寫（CLI 目前固定走預設值）。

**重跑一致性**（除 `meta.fetchedAt` 外逐字可重現）：

```bash
.venv/bin/arena fetch-models && cp data/models.json /tmp/models-a.json
.venv/bin/arena fetch-models
diff <(jq 'del(.meta.fetchedAt)' /tmp/models-a.json) \
     <(jq 'del(.meta.fetchedAt)' data/models.json)   # 無輸出＝一致
```

沒有 `jq` 時等價檢查：

```bash
.venv/bin/python - <<'PY'
import json
a = json.load(open('/tmp/models-a.json'))
b = json.load(open('data/models.json'))
a['meta'].pop('fetchedAt')
b['meta'].pop('fetchedAt')
print('一致' if a == b else '不一致')
PY
```

### collect（社群收集，任務 C2）

以 **vendored** 的 `last30days` 引擎抓近 30 天 **Reddit／Hacker News／X（Twitter）**
貼文，落地成 `data/evidence/YYYY-MM-DD.jsonl`（UTC 日期）。引擎原始碼在
`vendor/last30days/`（pin commit `084662b501fb0dba95bd55eff0c258d35e0dc499`），
來源與升級方式見 `vendor/last30days/README.md`。

**Python 需求（重要）**：引擎需要 **Python >= 3.12**。`arena collect` 會優先使用
`<repo>/.venv/bin/python`；若該檔不存在則用目前解譯器，版本太舊會直接報錯並附指令。
可用 `ARENA_ENGINE_PYTHON` 指定其他 3.12+ 解譯器。

```bash
# 抓 config/models.yaml 全部模型（預設近 30 天、模型間隔 30 秒避免限流）
.venv/bin/arena collect

# 只抓指定模型（id 或 name），放大間隔
.venv/bin/arena collect --models "Claude Opus 5.5" "GPT-6 Sol" --sleep 35

# 高召回模式與窗口天數
.venv/bin/arena collect --deep --days 60
```

**來源與憑證**：每次查詢都以 `--search reddit,hackernews,x` 明確要求三個來源
（X 需憑證才會啟用，見下）。X 的 agent JSON 沒有 `author` 欄位，但 `url` 是
`https://x.com/<handle>/status/<id>` 永久連結，`author` 直接由路徑取得（`@handle`），
不需要 `enrich` 補缺。

X 憑證放在 **`~/.config/last30days/.env`**（不放 repo、不進版控），可用下列任一方式：

- `AUTH_TOKEN` ＋ `CT0`：瀏覽器登入 X 後的 cookie 值（引擎的 `bird` 後端使用）。
- `XAI_API_KEY`：xAI API key。

沒放憑證時會**優雅降級**：`--search` 仍要求 X，引擎對 X 回報
`skipped-unconfigured`，`collect` 視為「預期跳過」——明確警告、不重試、不影響
退出碼，Reddit／HN 照常收集（CI 等無憑證環境也能跑）。

流程重點：

- **粒度：留言逐則（裁定 13）**：Reddit／HN 的**主貼不評分**（社群主貼多為提問、
  不帶態度），每個討論串改取**熱門前 10 則留言**，**每則留言各自成一筆**：
  `url` 是留言永久連結、`author` 是留言者、`postedAt` 是留言時間、`text` 是留言原文。
  留言不足 10 則照實取，0 則則該串不產生資料。X 維持每則推文一筆（X 池無留言結構）。
  留言來源：Reddit `.json`（本環境 keyless 一律 403，自動退到 Reddit 仍免 key 開放的
  shreddit 留言端點 `/svc/shreddit/comments/r/<sub>/t3_<id>`，已實測可用）、
  HN Algolia `/api/v1/items/<id>`（免 key）。> HN 不公開留言分數，故 HN 依 Algolia
  回傳的樹狀順序（上層留言優先）取前 10 則，不是依熱門度排序。
- **過濾**：只留 `reddit`／`hackernews`／`x`（`source` 白名單，擋掉 jobs 等雜訊）；
  排除非英文貼文（拉丁字母比例 < 0.6；評分 rubric 為英文）；缺 `url`／時間者丟棄。
- **歸屬：版本精確比對（裁定 14，取代 C6 的歸屬三態）**：文字必須以**精確版本**提及
  query 模型才採計（`Sonnet 5.5` 命中 `claude-sonnet-5.5`、`gpt-6-astra` 也算），
  版本後不得再接數字，故 `5.5` 不會命中 `5.55`。只提品牌字無版本號 → 丟
  （`只提品牌字`）；提到「家族＋版本」但該版本不在清單（`Gemini 3.8`、`Sonnet 4.5`）
  → 丟並計入 `誤歸屬`；完全沒提模型 → 丟（`沒提任何模型`）。暱稱與變體後綴
  （Prime／Flash／FlashX／Max／Sol／Luna／Terra／Astra）**必須綁定世代**：
  `GPT-6 Sol` ≠ `GPT-5.6 Sol`、`GLM 5.3 Prime` ≠ `GLM 5.3 Flash`；只有該世代在清單
  裡獨佔一席時，社群只寫世代也算命中（例：`Gemini 2.5`）。規格型變體
  （`Qwen3.8-27B`／`Qwen3.8-2.4T`，即 `\d+[bmt]`）也當變體綁世代，
  不會被算成 `Qwen3.8 Max` 的證據。
- **`text`**：X 是 `title` ＋ `summary` 合成、Reddit／HN 是留言原文，一律
  **截斷至 1200 字元**（控制單則的評分 prompt 大小與成本）。
- **`hash`**：正規化文字（小寫、空白壓扁）的 sha256，**跨所有 evidence 檔去重**
  （同批與跨檔都比對，跨來源轉貼亦然），重複只留一筆。
- **補缺**：Reddit／HN 的 row 是留言，`author` 與留言永久連結都由留言 API 直接帶回；
  只有留言者未知（`[deleted]`／機器人）才留 `null`，不阻擋流程。X 的作者由永久連結
  取得。`votes`／`judge` 由 `arena score`（C8 評審團）回填。
- **`source_status`**：只有 `ok`／`no-results` 視為正常；`skipped-unconfigured`
  是預期跳過（見上）；`rate-limited` 等失敗狀態會退避重試
  （`--retries`／`--retry-backoff`），仍失敗則明確警告、不當成「沒討論」。
- **冪等**：同一天重跑採「讀入→合併去重→原子寫回」（先寫同目錄暫存檔再
  `os.replace`），不會產生半截檔案；重跑不重複寫入。
- **離線防護**：偵測到 pytest 環境（或 `ARENA_OFFLINE=1`）且未注入 runner 時會
  停止連網；確定要連網可設 `ARENA_ALLOW_NETWORK=1`。

Reddit 的 keyless 路徑會限流；連續抓多個模型時請保留 `--sleep`（預設 30 秒）。

```bash
# 產生後驗證（結構合法但未評分的 evidence 也應回 0）
.venv/bin/arena validate data/evidence/*.jsonl
```

舊池（`data/evidence/2026-09-29.jsonl`，粒度為「一個討論串」且歸屬規則過寬）
已依裁定 14 搬至 `data/evidence/archive/`。`build`／`score` 的 glob 是
`data/evidence/*.jsonl`（非遞迴），**archive 不會被掃到**，可留作稽核對照。

### build（聚合成 scores.json，任務 C4）

讀 `data/evidence/*.jsonl` 與 `data/models.json`，由 evidence 的 `votes` 聚合出
`data/scores.json`。**分數全部由公式算出，模型不直接打分**：

- 只計**已評分**的列（`judge` 為 `llm-jury@<hash>`、`votes` 六鍵完整）；`votes` 為 `null`
  的未評分列會跳過並在 stderr 報數量。
- 每面向 `P`＝positive 數、`N`＝negative 數、`n = P + N`（`not-discussed` 不計入）；
  `n = 0` → 該面向 `null`（「資料不足」，不得當成 50）。
- `raw = (P − N) / n`，`dimScore = 50×(raw+1)×n/(n+K) + 50×K/(n+K)`，`K = 10`
  為偽樣本數收縮（n=10 收一半、n=90 收 10%；樣本越小越往 50 靠攏），四捨五入到小數第一位。
  例：`n=10` 全正 → `75.0`。
- 總分 `score`＝非 null 面向的加權平均（權重 `meta.weights`，剔除 null 後**重歸一**），
  以四捨五入後的面向分數計算，讓榜上數字可手算回推。
- 模型層 `confidence`＝overall 正面率的 **Wilson 95% 下界**（z=1.96）。
- `sampleSize = 0` 的模型**不入榜**，並列在 `meta.notes` 交代排除清單。
- `evidence` 參照列出該模型**全部**的列（含未評分者），格式 `evidence/<檔名>#l<行號>`。

輸出採原子寫入（先寫同目錄暫存檔再 `os.replace`、chmod 644），寫完自動以
`validate_path` 驗證；**不合規則就不覆蓋原檔**並以非 0 結束碼收場。

```bash
# 依 data/evidence/*.jsonl 與 data/models.json 產出 data/scores.json（並自動 validate）
.venv/bin/arena build

# 指定窗口天數與輸出檔
.venv/bin/arena build --window-days 60 --output /tmp/scores.json
```

**重跑一致性**（除 `meta.generatedAt` 與各模型的 `updatedAt` 外逐位元組相同）：

```bash
.venv/bin/arena build && cp data/scores.json /tmp/scores-a.json
.venv/bin/arena build
.venv/bin/python - <<'PY'
import json
a = json.load(open('/tmp/scores-a.json'))
b = json.load(open('data/scores.json'))
for doc in (a, b):
    doc['meta'].pop('generatedAt')
    for model in doc['models']:
        model.pop('updatedAt')
print('一致' if a == b else '不一致')
PY
```

## C5 校準流程（gold 考卷，2026-09-30 定案）

gold v2 由**四家真 LLM**（qwen3.8-flash／mimo-v2.6-flash／minimax-m3／
nemotron-3.5-lightning）以 OpenRouter API **逐則、溫度 0** 標註（規則照
`docs/annotation-guide.md` v1.2），≥3/4 多數定案 117 列。第一輪「四家標註」因部分
出自 regex 腳本冒名、出身不可驗證，已**全部作廢重做**；出身可由
`tools/annotate_gold.py`＋API 帳單重現。

```bash
# 1. 由 evidence 重新抽樣標註工作檔（固定 seed，同池重跑位元組相同）
.venv/bin/python -m arena.calibrate sample

# 2. 四家真 LLM 逐則標註（各跑一次；可續跑，已標 hash 自動跳過）
export OPENROUTER_API_KEY=sk-or-...
.venv/bin/python tools/annotate_gold.py --model qwen/qwen3.8-flash \
  --annotator qwen3.8-flash --out data/calibration/real/annotations-qwen3.8-flash.jsonl

# 3. 合併四家標註 → gold（≥3/4 多數；不足則該列記 ambiguous）
.venv/bin/python tools/merge_gold.py --inputs data/calibration/real/annotations-*.jsonl

# 4. 對同一批貼文跑 arena score 後，做「評審團 vs gold」驗證
.venv/bin/python tools/eval_jury_vs_gold.py --gold data/calibration/gold-v2.jsonl \
  --scored data/evidence/archive/2026-09-29.jsonl \
  --out docs/calibration-report.md --json docs/calibration-report.json
```

驗證門檻（owner 裁定 2026-09-30）：overall accuracy ≥ 0.80；五個面向改比
「accuracy 須勝過常數 not-discussed baseline」（not-discussed 佔九成時，絕對
0.80 是誤導性指標）；「有討論列數」< 10 的面向標『樣本不足』。最新結果：
**overall 0.8174 ✅**，報告見 `docs/calibration-report.md`。

> 舊版流程（laya-evals 本地校準、`arena calibrate make-evals`）隨 laya 淘汰，
> 僅保留於 git 歷史與 `docs/research/laya-usage-accuracy.md`。

## 注意事項

- 近 30 天窗口＝**近期聲量**，會偏袒剛發布／剛洗版的模型，輸出必須標示。
- **樣本數不等於人氣**：搜尋引擎每次查詢有回傳上限（每來源 `per_stream_limit=12`、
  `pool_limit=40`），各模型筆數趨於平均是截斷造成的假象。榜單呈現須以「社群聲量
  代理指標」定位，不要把 `sampleSize` 當成熱門度條。
- 現在一筆＝**一則留言／推文**，單一模型樣本量小（2~25）＋K=10 收縮，分數會集中在
  50 附近；呈現務必帶樣本數與 `confidence`，並把「樣本不足」的面向照實標示。
- 不要讓模型直接「打一個分數」，分數必須可由公式重算。
- 現在**不需要資料庫**：原始證據與分數都以檔案進 git，有 commit history 可追溯。
