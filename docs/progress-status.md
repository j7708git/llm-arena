# llm-arena 進度交接單（2026-09-30，PM 更新——C8 完成、gold v2 定案、驗證有結果）

> 用途：供後續 agent session（研究／實作／交接）快速接手。
> 權威文件：`docs/plan.md`（契約 v1.2＝LLM 評審團，裁定第 12 條）、
> `docs/annotation-guide.md`（v1.2）、`docs/research/*.md`、`docs/calibration-report.md`（新）。
> 本單只是快照，與 plan.md 衝突時以 plan.md 為準。

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

## 2. C5 校準：C8 評審團驗證結果（2026-09-30，gold v2 定案）

**gold v2 出身聲明**：第一輪「四家標註」被發現部分出自 regex 腳本冒名（annotate.py）或
session 手寫判斷表，**已全部作廢重做**——四家真 LLM（qwen3.8-flash／mimo-v2.6-flash／
minimax-m3／nemotron-3.5-lightning）逐則 API 標註、溫度 0、v1.2 規則，≥3/4 多數成 gold，
117 列定案（33 列平手/缺答案記 ambiguous）。出身可重現：`tools/annotate_gold.py`＋API 帳單。

評審團（`llm-jury@cd50a7e9`）vs gold（n=115，詳 `docs/calibration-report.md`）：

```
overall        0.8174 ✅（門檻 0.80；laya 只有 0.4424）
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

- **面向門檻設計（已裁定 2026-09-30）**：overall ≥ 0.80；五面向改「accuracy 須勝過常數
  ND baseline」，有討論列數 <10 的面向標『樣本不足』（speed 7／tokenEfficiency 1／
  tokenUsage 2／priceValue 9 皆屬此類，呈現須標可信度）。新門檻下總判定 ✅ 過關。
  quality 是唯一有足夠樣本（28 列）且勝過 baseline 的面向（0.7652 vs 0.7565）——
  未來若要加強，收集「有聊智能品質」的貼文最能補強該面向。
- **單一評審收斂**：juryVotes 逐票數據累積中，等一致率樣本夠多再評估 qwen3.7-flash 單飛
- 排程頻率（每日／每週）未定；`meta.judge.calibrated` 維持 `false`，待 owner 認可新
  門檻下的驗證結果後再改 `true`（plan.md 裁定 5）
- C2 歸屬漏洞：清單外新模型（Astra／Fable／Luna…）的貼文會進池，清單要定期擴充或
  collect 端加黑名單——尚未開任務卡
- jason-lab 端尚未動工；`data/scores.json`（真資料版）＋種子 `data/samples/` 都是它可用的開發資料

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
