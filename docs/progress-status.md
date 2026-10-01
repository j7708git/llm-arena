# llm-arena 進度交接單（2026-09-30，PM 更新——C8 完成、gold v2 定案、驗證有結果）

> 用途：供後續 agent session（研究／實作／交接）快速接手。
> 權威文件：`docs/plan.md`（契約 v1.2＝LLM 評審團，裁定第 12 條）、
> `docs/annotation-guide.md`（v1.2）、`docs/research/*.md`、`docs/calibration-report.md`（新）。
> 本單只是快照，與 plan.md 衝突時以 plan.md 為準。

## 1. 管線狀態（全部 commit，工作樹髒的只有進行中的標註檔）

| 模組 | 命令 | 狀態 | commit |
| --- | --- | --- | --- |
| fetch-models | `arena fetch-models` | ✅ **人工清單 v2：15 模型**（保留 5＋A 檔 5＋B 檔 5）＋OpenRouter 定價/context，缺欄標記、掛掉降級；15 席於 2026-10-01 實查全部有定價（0 缺欄） | `16fa0a5`＋C9 |
| collect | `arena collect` | ✅ last30days 引擎（vendor，pin `084662b`）× reddit/hn/x；**C9：Reddit／HN 留言逐則（每串熱門前 10 則）、歸屬改版本精確比對**、去重、原子寫入 | `abf10af`＋C2b/C6＋C9 |
| score | `arena score` | ✅ **C8：LLM 評審團**（現為 qwen3.7-flash 單一評審，schema v1.2）；laya 已淘汰（保留程式碼） | `2308e40`→C8→單飛 |
| build | `arena build` | ✅ votes→分數（K=10 收縮＋Wilson confidence），自動 validate | `67959d8` |
| validate | `arena validate` | ✅ schema v1.1／v1.2（pydantic，extra=forbid） | A2＋A3 |
| calibrate | `python -m arena.calibrate sample/make-evals/stats` | ✅ 抽樣＋gold 工具 | `107764a` |

**池現況（C9）**：

- 舊池 `data/evidence/2026-09-29.jsonl`（216 筆，粒度為「一個討論串」、8 模型）
  已搬至 **`data/evidence/archive/2026-09-29.jsonl`**（裁定 14：粒度與清單都變了，
  不清洗重用）。`build`／`score` 的 glob 是 `data/evidence/*.jsonl`（非遞迴），
  archive **不入聚合**，只留作稽核對照。
- 新池（2026-10-01 重收集）為**留言級**、清單 v2 15 席，實際筆數與分布見本單第 7 節。

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

## 8. 快速上手指令

```bash
cd /home/user/workspace/agent/llm-arena
.venv/bin/python -m pytest -q          # 231 passed, 3 skipped
.venv/bin/python -m arena.calibrate stats
.venv/bin/arena fetch-models           # 清單 v2：15 席
.venv/bin/arena collect                # 留言逐則重收集（慢，丟背景）
.venv/bin/arena score                  # 需 OPENROUTER_API_KEY（qwen3.7-flash 單評審）
.venv/bin/arena build && .venv/bin/arena validate data/scores.json data/evidence/*.jsonl
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
