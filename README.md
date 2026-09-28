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
.venv/bin/arena build         # 尚未實作的子命令會以非 0 結束碼回報

# 4. 跑測試
.venv/bin/python -m pytest
```

也可以不啟用虛擬環境，直接用 `python -m arena` 執行（需先安裝專案）。

尚未實作的子命令會印出「尚未實作」訊息並以結束碼 `3` 收場，不會靜默成功。

## 注意事項

- 近 30 天窗口＝**近期聲量**，會偏袒剛發布／剛洗版的模型，輸出必須標示。
- 不要讓模型直接「打一個分數」，分數必須可由公式重算。
- 現在**不需要資料庫**：原始證據與分數都以檔案進 git，有 commit history 可追溯。
