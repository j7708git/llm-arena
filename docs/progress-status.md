# llm-arena 進度交接單（2026-10-02，實作者更新——C10 完成：歸屬繼承主貼、池回到千筆以上）

> 用途：供後續 agent session（研究／實作／交接）快速接手。
> 權威文件：`docs/plan.md`（`scores.json` 契約 v1.2＝LLM 評審團，裁定第 12 條；
> evidence v1.3＝可選 `thread` 欄位，裁定 15）、
> `docs/annotation-guide.md`（v1.2）、`docs/research/*.md`、`docs/calibration-report.md`（新）。
> 本單只是快照，與 plan.md 衝突時以 plan.md 為準。

## 1. 管線狀態（全部 commit，工作樹髒的只有進行中的標註檔）

| 模組 | 命令 | 狀態 | commit |
| --- | --- | --- | --- |
| fetch-models | `arena fetch-models` | ✅ **人工清單 v2：15 模型**（保留 5＋A 檔 5＋B 檔 5）＋OpenRouter 定價/context，缺欄標記、掛掉降級；15 席於 2026-10-01 實查全部有定價（0 缺欄） | `16fa0a5`＋C9 |
| collect | `arena collect` | ✅ last30days 引擎（vendor，pin `084662b`）× reddit/hn/x；**C9：Reddit／HN 留言逐則、歸屬改版本精確比對；C10：主貼定歸屬＋留言繼承（每串前 20 則）、evidence 加 `thread` 欄位**、去重、原子寫入 | `abf10af`＋C2b/C6＋C9＋C10 |
| score | `arena score` | ✅ **C8：LLM 評審團**（現為 qwen3.7-flash 單一評審，schema v1.2）；laya 已淘汰（保留程式碼） | `2308e40`→C8→單飛 |
| build | `arena build` | ✅ votes→分數（K=10 收縮＋Wilson confidence），自動 validate | `67959d8` |
| validate | `arena validate` | ✅ schema v1.1／v1.2（pydantic，extra=forbid）；**evidence v1.3（可選 `thread`）同收** | A2＋A3＋C10 |
| calibrate | `python -m arena.calibrate sample/make-evals/stats` | ✅ 抽樣＋gold 工具 | `107764a` |

**池現況（C10）**：

- 舊池 `data/evidence/2026-09-29.jsonl`（216 筆，粒度為「一個討論串」、8 模型）
  已搬至 **`data/evidence/archive/2026-09-29.jsonl`**（裁定 14：粒度與清單都變了，
  不清洗重用）。`build`／`score` 的 glob 是 `data/evidence/*.jsonl`（非遞迴），
  archive **不入聚合**，只留作稽核對照。
- 新池 `data/evidence/2026-10-01.jsonl` 為**留言級**、清單 v2 15 席，C10 重收集後
  **1455 筆**（實際筆數與分布見本單**第 8 節**；第 7 節是 C9 的歷史快照）。

## 2. C5 校準：C8 評審團驗證結果（2026-09-30，gold v2 定案）

**gold v2 出身聲明**：第一輪「四家標註」被發現部分出自 regex 腳本冒名（annotate.py）或
session 手寫判斷表，**已全部作廢重做**——四家真 LLM（qwen3.8-flash／mimo-v2.6-flash／
minimax-m3／nemotron-3.5-lightning）逐則 API 標註、溫度 0、v1.2 規則，≥3/4 多數成 gold，
117 列定案（33 列平手/缺答案記 ambiguous）。出身可重現：`tools/annotate_gold.py`＋API 帳單。

評審團（`llm-jury@cd50a7e9`）vs gold（n=115，詳 `docs/calibration-report.md`）：

```
overall        0.8174 ✅（門檻 0.80。laya 的 0.4424 是在已作廢的舊 gold 上量得，
               與本結果沒有直接對比，不得併列解讀）
quality        0.7652 ❌（常數ND baseline 0.7565——僅小幅勝出）
speed          0.9652 ✅
tokenEfficiency 0.9739 ✅（但低於常數 baseline 0.9913）
tokenUsage     0.9913 ✅
priceValue     0.9739 ✅
來源切片：hn 0.878／reddit 0.781／x 0.765
```

**判讀**：overall 大幅過線、榜單可用；但各面向（not-discussed 佔九成）只小幅勝過
「全猜 not-discussed」常數 baseline——R4 預測的指標設計問題屬實。
**待 owner 決策**：(a) 面向門檻改「勝過常數 baseline」而非絕對 0.80，或 (b) 維持門檻
並接受 quality 面向偏弱（主要誤差：neutral 貼文被評審團判 positive，11/90）。

**歷史對照（第一輪假 gold 上的 laya 成績，僅供參考）**：舊 gold（部分出身不可驗證）上
laya n=110 preview：choice_accuracy 0.4424 FAIL／ECE 0.1342 FAIL／信心與正確率倒掛。
混淆矩陣病灶：gold 約 9 成是 `not-discussed`，laya 幾乎每則硬給態度。此結論在真 gold v2
上由評審團驗證結果取代（見上）。

## 3. 方向 B 結論（歷史，已被 C8 取代）

- **R4/R5 研究**（`docs/research/laya-usage-accuracy.md`、`jev-variants-survey.md`）：
  laya 官方 self-eval 同族任務 0.442 → 病灶是 domain fit，不是問法；JEV 變體普查
  194 專案無已證實更優者；成本論證失效（LLM 評審一趟 $0.13）。
- **C8 評審團上線**：`arena score` 改四人評審團（契約 plan.md 裁定 12），216 筆真資料
  已重評、v1.2 榜單已產（commit `90751d7`）。qwen3.7-flash 列為觀察員，等更多
  一致率數據再決定是否收斂單一評審。

## 5. 進行中／待決

- **2026-10-01 新裁定（owner，網站上線後發現榜單被張冠李戴污染）**：
  1. 評分粒度改「留言逐則」——Reddit/HN 主貼不評分，每串取熱門前 10 則留言各自成
     row；X 照舊（裁定 13，plan.md）。
  2. 清單 v2——移除 Sonnet 4／GPT-5／DeepSeek V3.1，保留 Gemini 2.5 Pro（X 上真討論），
     新增 A 檔＋B 檔共 10 個新模型（裁定 14，plan.md；證據見
     `docs/research/model-roster-survey.md`，清單確認以 X 池為準）。
  3. 歸屬規則收緊：版本精確比對、品牌字無版本丟、清單外丟、alias map（裁定 14）。
  4. 舊池不清洗重用，搬 `data/evidence/archive/`，以新規則重收集。
  任務卡 `.openchamber/plans/llm-arena-c9-collect-v2.md`；**實作狀態見第 7 節**。
- **2026-10-02 新裁定（owner，C9 樣本反而變少）**：
  1. **歸屬與情緒分離**——主貼（title＋body）決定該串歸屬的模型，每則留言繼承該串，
     情緒仍逐則判（裁定 15）。留言自己精確提到清單內某版本時歸那個；清單外版本／
     他家族品牌字 → 丟；完全不提模型 → 繼承。**實作狀態見第 8 節**。
  2. 每串留言上限 10 → 20（Reddit 依 score、HN 維持 Algolia 樹狀順序）。
  3. evidence schema **v1.3**：留言 row 新增可選 `thread`＝`{url, title, modelId}`
     記錄歸屬依據；X 推文不帶；`scores.json` 契約不變（仍 v1.2）。
  4. 待 owner 裁定（契約張力，實測 20/1455 筆）：主貼**標題**不帶版本號時，
     `thread.title` 撐不起歸屬，修正選項見第 8 節落差 1。
- **面向門檻設計（已裁定 2026-09-30）**：overall ≥ 0.80；五面向改「accuracy 須勝過常數
  ND baseline」，有討論列數 <10 的面向標『樣本不足』（speed 7／tokenEfficiency 1／
  tokenUsage 2／priceValue 9 皆屬此類，呈現須標可信度）。新門檻下總判定 ✅ 過關。
  quality 是唯一有足夠樣本（28 列）且勝過 baseline 的面向（0.7652 vs 0.7565）——
  未來若要加強，收集「有聊智能品質」的貼文最能補強該面向。
- **單一評審收斂（已裁定並執行 2026-10-01）**：owner 選擇 A——`arena score` 改由
  **qwen3.7-flash 單飛**（judge=`llm-jury@557e1059`）。依據：gold v2 上單飛 0.852
  並列第一、過 0.80 門檻，成本 1/16。多數決機制保留（改 `JURY_MEMBERS` 即可擴編）。
  但書：qwen3.8-flash 是 gold 標註者之一（同家族風險）；且僅一次考試樣本——
  未來每次跑分持續觀察，若準確率跌破門檻再議擴編。
- 排程頻率（每日／每週）未定；`meta.judge.calibrated` 已改 `true`（owner 認可
  2026-09-30，plan.md 裁定 5）——`build.py` 預設值已同步改 `true`，重跑 build 不會回退
- C2 歸屬漏洞**已由裁定 14 收緊**（C9 落地）：清單外的「家族＋版本」貼文一律
  `misattributed` 丟棄，不再需要另開黑名單任務卡。但清單本身仍需定期擴充——
  新模型的討論在過嚴規則下會全被丟掉，直到它進 `config/models.yaml`
- jason-lab 端尚未動工；`data/scores.json`（真資料版）＋種子 `data/samples/` 都是它可用的開發資料

## 7. C9 實作現況（2026-10-01，清單 v2＋留言逐則）

> **歷史快照**：C10（2026-10-02）把歸屬改成「主貼定歸屬、留言繼承」並重收集，
> 本節的 126 筆／分布已被**第 8 節**取代。留在此供對照 C10 修正了什麼。

**程式面**（全部完成，`pytest` 231 passed 3 skipped）：

- `config/models.yaml`：15 席＝保留 5（sonnet-5.5／gpt-6-sol／gemini-2.5-pro／
  grok-4.7／glm-5.3-prime）＋A 檔 5（opus-5.5／sonnet-5／gpt-6-astra／glm-5.3-flash／
  deepseek-v4.1-flash）＋B 檔 5（qwen3.8-max-0902／opus-5／kimi-k3／claude-fable-5.1／
  gpt-5.6-luna）。`arena fetch-models` 實查 15 席**全部有定價與 context**（0 缺欄）。
- `collect.py` 歸屬：`classify_attribution()` 取代 C6 歸屬三態，比對鍵是
  `家族/等級/版本/變體`（`model_keys()`）。版本後不得再接數字（`5.5` 不命中 `5.55`）；
  品牌字無版本 → `dropped_brand_only`；清單外版本 → `misattributed`；沒提模型 →
  `dropped_no_mention`。暱稱綁世代（`GPT-6 Sol` ≠ `GPT-5.6 Sol`）；
  變體只在**同世代在清單裡不只一席**時才強制（`GLM 5.3` 有 Prime+Flash → 不接受
  裸世代；`Gemini 2.5` 僅 pro 一席 → 接受裸世代）。
- `enrich.py` 新增 `HttpCommentFetcher`：Reddit 每串熱門前 10 則留言
  （依 score 排序）、HN 前 10 則（Algolia `items/<id>`）；`build_comment_records()`
  讓每則留言各自成 evidence row（url/author/postedAt/text 取自留言）。

**實測到的三個現實落差（與 plan.md 契約的差異，如實記錄）**：

1. **Reddit `.json` 端點在本環境 keyless 一律 403**（2026-10-01 實測：換 UA、
   `old.reddit`、`api.reddit` 都一樣）。已實作 fallback 到 Reddit 仍免 key 開放的
   shreddit 留言端點 `/svc/shreddit/comments/r/<sub>/t3_<id>`（回 HTML，留言內嵌為
   `<shreddit-comment>` 元素，實測 200／22 則）。契約仍以 `.json` 為主路徑，
   403 才退到 shreddit；解析層兩者輸出同一結構，測試各有一條。
2. **HN 不公開留言分數**（Algolia 也沒有），所以「熱門前 10 則」在 HN 只能是
   **Algolia 樹狀順序（上層留言優先、depth-first）的前 10 則**，不是依熱門度。
   Reddit 有真 score，排序是真的。此差異需在站方文案說明「留言取樣方式」時一併交代。
3. **研究報告 §5 的 `qwen/qwen3.8-max` 在 OpenRouter 不存在**（2026-10-01 實查
   `/api/v1/models` 只有 `qwen/qwen3.8-max-0902` 與 `qwen/qwen3.8-max-prime`）。
   清單採實際存在的 `qwen/qwen3.8-max-0902`，顯示名仍為 `Qwen3.8 Max`。
4. **規格型變體要綁世代**（實作時補的規則，研究報告未列）：`Qwen3.8-27B`／
   `Qwen3.8-2.4T` 是不同的 SKU，若只比「版本＋Max」，這些貼文會被算成
   `Qwen3.8 Max` 的證據（首輪收集實際命中 16 筆）。故偵測式把
   `\d+[bmt]`（27b／30b／2.4t）也當變體，這 16 筆已在新池剔除。
5. **1 則 X 推文在驗收時已被刪**（`@rugnasyab/2105637339691426009`，X 回 404），
   連線全池複驗時剔除。X 來源有這種「抓到後被刪」的流失率，站方若要顯示
   單筆連結應容許偶發失效。

**新池現況**（`data/evidence/2026-10-01.jsonl`，`arena collect` 單趟 ~24 分鐘）：

- **126 筆**，來源 reddit 54／x 50／hn 23；**15 席全部有資料，無 0 筆者**。
- 分布（留言級後每模型筆數落差較大）：Opus 5.5 **25**、GLM 5.3 Flash **16**、
  Kimi K3 **13**、Sonnet 5.5 **9**、Grok 4.7 **9**、DeepSeek V4.1 Flash **9**、
  Opus 5 **8**、GPT-6 Astra **8**、Gemini 2.5 Pro **7**、GPT-5.6 Luna **7**、
  GPT-6 Sol **4**、GLM 5.3 Prime **4**、Qwen3.8 Max **3**、Sonnet 5 **2**、
  Fable 5.1 **2**。`author` 無 null（留言 API 都帶回留言者）。
- 收集摘要：15 模型、328 個討論串、無留言 49、**只提品牌字 409**、
  **沒提任何模型 1582**、**誤歸屬 410**（清單外版本）、非英文 32。
  規則擋掉的比例遠高於舊規則，但留下的每一筆都精確提及該模型版本。
- 驗收工具 `tools/verify_pool.py`：全池 126 筆 **url 皆可連回（HTTP 200）**、
  歸屬判定 0 不通過。
- 人工抽核 20 筆（`random.seed(20261001)`）逐筆看過：url 可連、留言／推文確實在談
  該 row 的版本。較邊緣但判定正確的兩例——
  `https://www.reddit.com/r/LocalLLM/comments/1woq7cd/.../pbp5qaz/`
  （講「Qwen 3.8」的推論引擎加速，該世代在清單裡只有 Max 一席故採計）、
  `https://www.reddit.com/r/LocalLLaMA/comments/1wpkz0o/.../pbwxtw8/`
  （一句裡同時提 GLM 5.3 Flash 與 DeepSeek，但 DeepSeek 未帶版本號，屬非模型命中）。

**score／build 已完成**（2026-10-02）：金鑰來源改 dotenv 鏈（環境變數 →
專案 `.env`（已指向中央金鑰檔 `~/.keys/.env`）→ 中央金鑰檔），程式見
`arena.jury.resolve_api_key`。`arena score` 已跑：126 則全數評分、0 次呼叫失敗
（judge=`llm-jury@557e1059`），`arena build` 產出 v2 榜單並通過 `arena validate`
（15 席、`sourcesCovered=[hn,reddit,x]`）。

**v2 榜單的判讀注意**（給站方與後續 session）：現在一筆＝一則留言，樣本本來就小
（2~25 筆），加上 K=10 收縮，分數集中在 43~60、`confidence` 普遍 0.0~0.34；
多數模型有多個面向標「樣本不足」。**Gemini 2.5 Pro 名列第 2（n=7）是緬懷文
小樣本效應，不是它真的比新模型強**——呈現務必帶樣本數與可信度。留言的情緒
比主貼更批判（最高正面率僅 0.52），符合預期但要寫進網站文案的說明。

## 8. C10 實作現況（2026-10-02，歸屬繼承主貼）

**為什麼做**：C9 把粒度改成「留言逐則」後，歸屬規則仍要求**每一則留言自己**精確寫出
模型版本，而留言幾乎不會重複寫（「它好爛」「這代超強」）。留下的 5 個模型從 143 筆
掉到 54 筆、新池總量 216→126，與「留言逐則應該讓樣本變多」相反。根因是歸屬證據在
主貼、情緒證據在留言，兩者卻被要求存在同一筆。裁定 15 的解法是**兩者分離**。

**程式面**（`pytest` 273 passed 3 skipped）：

- `collect.py`：主貼層級仍走 `classify_attribution()`（裁定 14 的版本精確比對），
  但**判定時點前移到抓留言之前**——串未通過歸屬就整串跳過，省下每串兩次留言 API。
  新增 `classify_comment_attribution()` 實作裁定 15 的五條優先序（留言自身精確提及 →
  歸它；清單外版本 → 丟；只提品牌字且屬串本身家族 → 繼承；只提品牌字且屬其他家族 →
  丟；完全不提模型 → 繼承），以及 `brand_families()`（判斷品牌字屬哪個家族）。
  摘要會分開報「自身精確提及／繼承主貼」兩種歸屬來源。
- `enrich.py`：每串留言上限 10 → **20**（`TOP_COMMENTS`）。Reddit 依 score 排序、
  HN 維持 Algolia 樹狀順序（上層優先）——HN 不公開留言分數這點**不變**，已在
  README 與本單註明。
- 新增 `HttpCommentFetcher.thread_url()`：HN 的引擎結果 url 常指向外部原文，
  `thread.url` 改用 Algolia 以標題回查的 `news.ycombinator.com/item?id=...`；
  Reddit 的 url 本身就是永久連結。查不到就沿用原 url，不讓整串失敗。
- `schema.py`：evidence 加**可選** `thread`（`ThreadRef`＝`{url, title, modelId}`），
  即 **evidence schema v1.3**。`scores.json` 契約不變（仍 v1.2）。`validate` 同一個
  `EvidenceRecordV12` 即同時接受 v1.2（無 `thread`）與 v1.3（有 `thread`）。
  X 推文與 v1.2 舊列的 `thread` 為 null 時**整欄省略**，不落地成 `"thread": null`。
- `tools/verify_pool.py`：歸屬判定改為「自身提及 **或** 繼承自 `thread.title`」，
  輸出兩種來源分布，並檢查 `thread` 欄位完整性（X row 不得帶 `thread`）；
  `--sample N --seed S` 讓人工抽核可重現，並印出留言／主貼標題原文供核對。

**新池現況**（`data/evidence/2026-10-01.jsonl`，單趟 collect 約 27 分鐘）：

- **1455 筆**（C9 的 126 筆仍在同一檔，另加本輪 1329 筆；舊池
  `archive/2026-09-29.jsonl` 不動）。來源 reddit 970／hn 377／x 108。
- **1270 筆留言帶 `thread` 欄位**（95 個討論串，平均 13.4 則／串，上限 20），
  108 筆 X 推文與 77 筆 C9 舊留言列不帶（v1.2 形狀，validate 照收）。
- 歸屬來源：留言**自身精確提及 240 筆（16.5%）**、**繼承自主貼 1195 筆（82.1%）**，
  20 筆不通過（見下「契約張力」）。繼承比例遠高於自身，正說明歸屬與情緒分離後
  樣本才回得來。
- 分布（依總數）：GPT-6 Astra 311、Opus 5.5 239、Grok 4.7 154、DeepSeek V4.1 Flash
  148、Kimi K3 119、Fable 5.1 114、GLM 5.3 Flash 94、GPT-6 Sol 79、Sonnet 5.5 66、
  GPT-5.6 Luna 58、Opus 5 29、Qwen3.8 Max 22、Gemini 2.5 Pro 16、GLM 5.3 Prime 4、
  **Sonnet 5 只有 2 筆**。
- 28 筆（2.2%）的 `modelId` ≠ `thread.modelId`：留言自己精確提到另一個清單模型而改判
  （例：GPT-6 Sol 串裡有人說「Opus 5.5 seems better?」→ 該則歸 Opus 5.5）。
  這正是 `thread.modelId` 存在的意義——能分辨「繼承」與「改判」。
- 收集摘要：15 模型、330 個討論串、**串未通過歸屬 214**（誤歸屬 181、只提品牌字 33）、
  無留言 16、留言抓取失敗 0；留言判定為自身精確提及 98（其中只提品牌字而繼承同家族
  133）、繼承主貼 1218，丟棄清單外版本 70／他家族品牌字 89／多模型 18／誤歸屬 121。

### 遇到的現實落差（與 plan.md 契約的差異，如實記錄）

1. **裁定 15 內部的張力：主貼標題不帶版本號的串**。第 1 條用「主貼 title＋body」
   判歸屬，第 4 條的 `thread` 卻只記 `title`，第 5 條的驗收又要求 `thread.title`
   精確提及該模型。實測有 **20 筆**（1.4%）來自同一個 Reddit 串
   （`r/ClaudeCode/comments/1wov62z`，標題 "got mogged by claude opus 😭"，版本號只
   出現在內文），`thread.title` 單獨撐不起歸屬 → `verify_pool` 如實報為不通過。
   **未自行改契約**（依邊界指示），修正選項：(a) `thread.title` 改記 title＋body；
   (b) 判定改只看標題（會少掉這串）；(c) schema 加第 4 欄記 body。請 owner 裁定。
2. **摘要印表的措辭 bug（已修）**：本次 collect 印出的
   「自身精確提及 98（其中只提品牌字而繼承同家族 133）」括號位置寫錯了——133 其實是
   繼承 1218 的子集合，不是 98 的子集合。各欄數字本身正確，錯的是給人看的措辭；
   已改成「繼承主貼 N（其中只提同家族品牌字 M）、自身精確提及 K」。
3. **collect 的輸出檔名依 UTC 日期**：本機 UTC 仍是 2026-10-01（CST 已是 10-02），
   故本輪寫進 `2026-10-01.jsonl` 而非 `2026-10-02.jsonl`。好處是 C9 的 126 筆與本輪
   1329 筆在同一個池檔裡（build／score 的 glob 照樣收兩者）；缺點是該檔混合兩種
   evidence 形狀（126+59 筆無 `thread`、其餘有），validate 兩種都收。
4. **「繼承」會帶進大量無立場留言**：這是裁定 15 的必然結果——純 jokes 與「+1」也會
   繼承該串（例如上面那個「got mogged by claude opus」串的 20 則留言幾乎全是
   吐槽）。評審會把它們判成 neutral／not-discussed。
   **實測**：繼承列的 overall 有 **704/1195（58.9%）是 neutral**，自身提及列只有
   98/240（40.8%）。**已由裁定 16 處理**：neutral 不再進 `positiveRate` 分母，
   並以 `dimensionSamples.overall` 揭露有表態筆數；站方文案仍須說明
   「一則留言＝一則社群留言，歸屬可能繼承主貼」。

**驗收結果**（2026-10-02）：

| 項目 | 結果 |
| --- | --- |
| 新池筆數 | **1455 筆**（千筆以上 ✅），15 席全部有資料 |
| 歸屬來源 | 自身 240（16.5%）／繼承 1195（82.1%）／不通過 20（1.4%，見落差 1） |
| `thread` 欄位 | 1270 筆帶、三欄齊全；108 筆 X 推文**皆不帶** ✅ |
| `thread.url` | Reddit 916 筆皆為 `…/comments/…` 主貼；HN 354 筆**全部**由 Algolia 回查成 `news.ycombinator.com/item?id=…` ✅；**95 個不重複主貼全數連線 2xx/3xx** ✅ |
| `arena validate` | `data/scores.json` ＋ `data/evidence/*.jsonl` 回 **0** ✅ |
| `arena score` | 1329 則全數評分、**0 次呼叫失敗**（judge=`llm-jury@557e1059`）、無效面向回覆 50 個（不影響該列其它面向） |
| `arena build` | 15 席全入榜；分數 40.7~59.6；`positiveRate`／`confidence` 於裁定 16 修正後為 **0.32~0.64／0.19~0.46**（分母＝有表態筆數，見 `dimensionSamples.overall`） |
| 重跑一致性 | 抽 12 則以同評審重評**兩輪**：144 格中 2 格不一致（1.4%）。唯一不一致的列是語意模糊的吐槽句（"All that effort for such a boring message…"），單獨重試 4 次得 neutral×2／negative×2 → **評審端本身非位元確定**（上游 provider），非管線邏輯問題。其餘 11 列逐格一致 ✅ |
| 人工抽核 | `verify_pool.py --sample 20 --seed 20261002`，20 筆 url 全 200；**14 筆情緒明確指向該模型**、6 筆合規但屬無立場／離題（純 gif、純語助詞、或談同串的**裸暱稱** sibling——裸暱稱不綁世代故不算提及，繼承該串）。全部符合裁定 15 五條優先序，無違例 |

**v3 榜單的判讀注意**（給站方）：樣本數分布極不平均（Sonnet 5 n=2、Prime n=4、
Gemini 2.5 Pro n=16 ↔ GPT-6 Astra n=311），名次幾乎由**樣本數**決定。
`positiveRate`／`confidence` 已按裁定 16 改為「有表態者中」計算：現在
**正面率 0.32~0.64、`confidence` 0.19~0.46**；`GLM 5.3 Prime`（4 筆全 neutral）
`positiveRate=0.0` 是**樣本不足**、不是全數不滿。低樣本席（n<20）務必標「僅供參考」。

## 9. 快速上手指令

```bash
cd /home/user/workspace/agent/llm-arena
.venv/bin/python -m pytest -q          # 273 passed, 3 skipped
.venv/bin/python -m arena.calibrate stats
.venv/bin/arena fetch-models           # 清單 v2：15 席
.venv/bin/arena collect                # 留言逐則重收集（慢，丟背景；實測約 27 分鐘）
.venv/bin/arena score                  # 需 OPENROUTER_API_KEY（qwen3.7-flash 單評審）
.venv/bin/arena build && .venv/bin/arena validate data/scores.json data/evidence/*.jsonl
# 池品質驗收（歸屬來源分布＋thread 欄位＋url 連線；抽樣可重現）
.venv/bin/python tools/verify_pool.py data/evidence/2026-10-01.jsonl --sample 20
# laya 評測（六題 CPU 很慢：110 筆跑 ~35 分鐘，务必丢背景）
USE_TF=0 LAYA_DEVICE=cpu .venv/bin/laya-evals run data/calibration/gold.jsonl \
  --model english --device cpu --batch-size 8 --min-accuracy 0.80 --max-ece 0.10 \
  --slice tag --json /tmp/opencode/... --markdown /tmp/opencode/...
```

坑摘要（詳見 research 筆記）：laya 載入的 choice:11+ 溫度 warning 屬正常；
score/laya-evals 在 CPU 都比網路宣稱慢（六題 ~3.5s/則）；test_cli dispatch 測試會
呼叫真命令，conftest 已把預設路徑導到 tmp，改管線時別繞過它。
**C9 新坑**：`arena collect` 一次跑 15 個模型、每模型一次引擎子行程＋每串兩次留言
API（Reddit shreddit 頁近 1MB），整趟要 20~40 分鐘，必須丟背景輪詢；
Reddit `.json` 403 已內建 fallback，不要以為抓不到資料是規則太嚴。
**C10 新坑**：輸出檔名取 **UTC** 日期，本機 CST 已跨日但 UTC 還沒跨時，資料會併入
前一天的檔（冪等合併，不會覆蓋）；`verify_pool.py` 判定歸屬要看 `thread.title`，
遇到主貼標題不帶版本號的串會如實報不通過（見第 8 節落差 1）。
