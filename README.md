# llm-arena

**Jason Lab** 的第一個工具：LLM 社群評價排行榜的**資料管線**。

這個 repo 只負責「產生可驗證的社群評價資料」，不負責網站外觀。
網站（[`jason-lab`](../jason-lab)）讀取本 repo 的資料產物來呈現排行榜。

- 定位：真的能跑、能重跑的評測工具，而不是展示品
- 狀態：**骨架階段**——CLI 五個子命令都已接上，功能陸續實作中（見 `docs/plan.md`）

## 產出什麼

| 檔案 | 內容 |
| --- | --- |
| `data/scores.json` | 算好的分數（網站唯一需要的輸入） |
| `data/evidence/*.jsonl` | 原始貼文與引用，讓每個分數都可回溯審核 |

## 方法（概要）

1. **模型清單**：以人工維護清單為主，附掛 OpenRouter 公開 API `https://openrouter.ai/api/v1/models` 的定價與 context length（用 API，不爬 HTML）。
2. **社群收集**：排程 agent 使用 `last30days` 技能抓近 30 天社群討論（Reddit／X／HN／論壇）。
3. **評分（兩層設計）**：
   - 慢層（做一次）：強推理模型 + rubric 定義「品質／速度／價格 CP 值」的判斷準則與邊界案例。
   - 快層（做很多次）：JEV 家族（自架 `laya` 或 `AgentJev-0.6B`）對逐則貼文分類態度並輸出**校準機率**（~50ms／則、不解碼 output token）。
4. **分數是算出來的**：以「正面提及比例 × 樣本數加權」計算，公式可驗證。

> 這是**社群聲量代理指標，不是 benchmark**。所有呈現都必須標明這點。

## 上線門檻（未達成前不得發布分數）

- [ ] 人工標註 100~200 則作為 ground truth，驗證準確率與**校準度**
- [ ] 去重機制（同一則爆紅貼文被轉貼多次只算一次）
- [ ] 送評時遮蔽模型名稱，避免評分器自我偏袒

## 目錄結構

```
src/               fetch-models / collect / score / build / validate
data/              scores.json、evidence/*.jsonl
tests/
docs/              plan.md、research/
```

## CLI（規劃中）

```bash
arena fetch-models   # 更新模型清單與定價
arena collect        # 抓取社群貼文（排程執行）
arena score          # JEV 逐則評分
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
.venv/bin/arena build         # 尚未實作的子命令會以非 0 結束碼回報

# 4. 跑測試
.venv/bin/python -m pytest
```

### 評分相依（`arena score`，任務 C3）

`arena score` 需要 `laya`（JEV 家族評分器，**CPU 可跑**）。它的 `torch` 預設會抓 CUDA
wheel，本機請指定 CPU backend：

```bash
uv pip install --python .venv/bin/python -e ".[score,dev]" --torch-backend=cpu
```

首次執行 `arena score` 會下載約 842MB 的英文 checkpoint（存進 Hugging Face 快取，
之後可離線重跑）。模型 revision、prompt、batch size 都固定在 `src/arena/score.py`，
選型理由與坑見 `docs/research/jev-scoring.md`。

```bash
# 對預設路徑 data/evidence/*.jsonl 逐則評分（laya，CPU）
.venv/bin/arena score

# 指定單一檔（score 子命令的 CLI 參數待 cli.py 解凍；目前先用環境變數）
ARENA_EVIDENCE_FILES=data/evidence/2026-09-29.jsonl .venv/bin/arena score

# 重評所有行，包含已有 label 的行（預設會跳過）
ARENA_SCORE_FORCE=1 .venv/bin/arena score
```

評分結果會把 `label`（positive／negative／neutral）、`prob`（＝laya 的 `answer_confidence`，
即校準機率）、`judge`（`laya@55cf4c4`）回填進 evidence。輸出採**原子寫入**（先寫同目錄
暫存檔再 rename），中途失敗不會留下半截 jsonl；已有 `label` 的行會跳過，因此可重複執行。

也可以不啟用虛擬環境，直接用 `python -m arena` 執行（需先安裝專案）。

尚未實作的子命令會印出「尚未實作」訊息並以結束碼 `3` 收場，不會靜默成功。

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

## 注意事項

- 近 30 天窗口＝**近期聲量**，會偏袒剛發布／剛洗版的模型，輸出必須標示。
- 不要讓模型直接「打一個分數」，分數必須可由公式重算。
- 現在**不需要資料庫**：原始證據與分數都以檔案進 git，有 commit history 可追溯。
