# llm-arena 進度交接單（2026-09-29 19:20，PM 產出）

> 用途：供後續 agent session（研究／實作／交接）快速接手。
> 權威文件：`docs/plan.md`（契約 v1.1＋裁定）、`docs/annotation-guide.md`（v1.2）、
> `docs/research/*.md`（R1/R2/R3）。本單只是快照，與 plan.md 衝突時以 plan.md 為準。

## 1. 管線狀態（全部 commit，工作樹髒的只有進行中的標註檔）

| 模組 | 命令 | 狀態 | commit |
| --- | --- | --- | --- |
| fetch-models | `arena fetch-models` | ✅ 人工清單8模型＋OpenRouter 定價/context，缺欄標記、掛掉降級 | `16fa0a5` |
| collect | `arena collect` | ✅ last30days 引擎（vendor，pin `084662b`）× reddit/hn/x；三態歸屬、去重、原子寫入 | `abf10af`＋C2b/C6 |
| score | `arena score` | ✅ **C8：LLM 評審團**（deepseek-v4.1-flash／glm-5.3-flash／gpt-6-luna／qwen3.7-flash，batch＋多數決、schema v1.2）；laya 已淘汰（保留程式碼） | `2308e40`→C8（工作樹未 commit） |
| build | `arena build` | ✅ votes→分數（K=10 收縮＋Wilson confidence），自動 validate | `67959d8` |
| validate | `arena validate` | ✅ schema v1.1（pydantic，extra=forbid） | A2＋A3 |
| calibrate | `python -m arena.calibrate sample/make-evals/stats` | ✅ 抽樣＋gold 工具 | `107764a` |

真資料池：`data/evidence/2026-09-29.jsonl` **216 筆**（reddit 82／hn 77／x 57，8 模型各 20~35 筆），
全部已帶 laya votes。榜單 `data/scores.json` 是 laya votes 的聚合——**若 judge 換人，重跑
`arena score`＋`arena build` 即可，聚合公式不動**。

## 2. C5 校準：目前的判決與數據（重要）

考卷（gold）產生方式：4 個不同家族 flash 模型（qwen3.8-flash／mimo-v2.6-flash／
minimax-m3／nemotron-3.5）獨立標 150 筆 → 每面向 ≥3/4 多數成 gold。owner 已拍板
**不做人類抽檢**（報告需如實寫「無人類 ground truth」）。

laya 成績（n=110 preview，`/tmp/opencode/llm-arena-c6/preview-evals.json`）：

```
choice_accuracy 0.4424（門檻 0.80）FAIL
ece             0.1342（門檻 0.10）FAIL
各面向 acc：priceValue .69／overall .60／tokenEfficiency .46／quality .39／speed .26／tokenUsage .25
信心分帶：facets conf≥0.75 的 accuracy=0.29 < 低信心組 0.43 → 信心與正確率「倒掛」，gating 不可用
來源切片：reddit .45／hn .48／x .35
```

混淆矩陣直指病灶：gold 約 9 成是 `not-discussed` 的面向，laya 幾乎每則都硬給態度
（例：tokenEfficiency 有 35 筆「沒談效率」被判 negative）。

## 3. 進行中的工作（交接對象要注意）

**v1.2 重標 40 筆平手列**（`data/calibration/redo-worksheet.jsonl`，四家重標）：
- ✅ 已到：`annotations2-qwen.jsonl`、`annotations2-minimax.jsonl`
- 🔄 進行中：mimo（`ses_f1331c4c9ffepDBCPJPGSx3xXC`）、nemotron 重試（`ses_f1322de6bffe72J8IZIY95QJS6`）
- 到齊後的合併步驟（與第一輪同法，腳本模式見 git log `6f24c9e` 前後）：
  1. 對 40 列逐格四家多數（≥3/4）→ 回填 `annotation-worksheet.jsonl` 對應列的六個 `gold_*`
     （該列必須六格全數有解才回填；仍平手的整列留 null → 記 `ambiguous` 排除，如實入報告）
  2. `python -m arena.calibrate make-evals` → 重產 `gold.jsonl`
  3. commit 數據
- 已知初步訊號：v1.2 規則下 qwen×minimax 同格一致率 0.79→0.91，預計多數列能收掉 35/40 上下。

**gold 定案後**：laya 用完整 gold（~140+）重跑一次正式評測，作為「laya 淘汰與否」的最終依據，
結果寫進 `docs/calibration-report.md`（尚未建立）。

## 4. 待研究：方向 B（owner 已選，待派 researcher）

owner 假設：「laya/JEV 是專門做即時決策的模型，官方 benchmark 有 GPT-5.6 Sol 級，
差距不太可能這麼大 → 可能是**我們問法**的問題」。任務卡：`.openchamber/plans/llm-arena-c7-laya-rescue-research.md`。

PM 補的警告（供研究者中立看待）：官方高分成績的题型是**結構化決策**（JevBench：
invoice／客服／安全／agent trace 的「該怎麼做」），不是「讀一則社群貼文判斷作者態度」——
先查 domain fit 再查 elicitation；另外 ex-ante 用同一份 gold 反覆試設計有 overfitting 風險，
要 held-out。

## 5. 其他未決（plan.md 待決事項鏡像）

- 排程頻率（每日／每週）未定；上線後才需要
- C2 歸屬漏洞：清單外新模型（Astra／Fable／Luna…）的貼文會進池（三態「兩者皆未出現→留」
  分枝），清單要定期擴充或 collect 端加「其他厂商模型名」黑名單——尚未開任務卡
- jason-lab 端尚未動工；`data/scores.json`（真資料版）＋種子 `data/samples/` 都是它可用的開發資料
- `meta.judge.calibrated` 目前 `false`（laya 未過線）；換 judge 後要同步改 `plan.md` 的 judge 定義
- **C8 換 judge 後 `arena build` 尚未跟上**（工作樹未 commit）：build 的 `_CANONICAL_JUDGES`
  仍只認 laya、`meta.judge` 仍寫 laya 形狀；真跑評審團、要重跑 `arena build` 前得先更新它
  （否則 llm-jury 的列會被當 judge 不符跳過）。屬 C8 後續步驟。

## 6. 快速上手指令

```bash
cd /home/user/workspace/agent/llm-arena
.venv/bin/python -m pytest -q          # 172 passed, 1 skipped
.venv/bin/python -m arena.calibrate stats
.venv/bin/arena validate data/scores.json data/evidence/2026-09-29.jsonl
# laya 評測（六題 CPU 很慢：110 筆跑 ~35 分鐘，务必丢背景）
USE_TF=0 LAYA_DEVICE=cpu .venv/bin/laya-evals run data/calibration/gold.jsonl \
  --model english --device cpu --batch-size 8 --min-accuracy 0.80 --max-ece 0.10 \
  --slice tag --json /tmp/opencode/... --markdown /tmp/opencode/...
```

坑摘要（詳見 research 筆記）：laya 載入的 choice:11+ 溫度 warning 屬正常；
score/laya-evals 在 CPU 都比網路宣稱慢（六題 ~3.5s/則）；test_cli dispatch 測試會
呼叫真命令，conftest 已把預設路徑導到 tmp，改管線時別繞過它。
