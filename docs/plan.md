# 開發計畫：llm-arena

總覽：`docs/plan-overview.md`
任務卡：`$HOME/workspace/agent/.openchamber/plans/llm-arena-*.md`
網站端計畫：`../jason-lab/docs/plan.md`

## 目標

產出一份**可驗證、可重跑、可回溯**的 LLM 社群評價資料集，供 `jason-lab` 網站呈現。

## 負責範圍

- ✅ 模型清單維護、社群貼文收集、評分、產出資料
- ❌ 網站外觀與頁面（屬於 `jason-lab`）
- ❌ 對外 API／即時查詢（未來若要做站內投票再評估）

## 資料契約（schema v1）

介面檔案：`data/scores.json`。**此 schema 凍結後才開始各自開發**；變更需同步 `jason-lab`。

```jsonc
{
  "meta": {
    "schemaVersion": 1,
    "generatedAt": "2026-09-29T00:00:00Z",
    "windowDays": 30,
    "kind": "community-sentiment",              // 明確標示不是 benchmark
    "disclaimer": "社群聲量代理指標，非 benchmark",
    "judge": { "model": "laya", "revision": "<sha>", "calibrated": true },
    "notes": "近 30 天窗口，會偏袒近期熱門模型"
  },
  "models": [
    {
      "id": "anthropic/claude-sonnet-4",
      "name": "Claude Sonnet 4",
      "provider": "Anthropic",
      "score": 72.4,
      "dimensions": {
        "quality": 78.1,
        "speed": 61.0,
        "price": 55.3,
        "priceUsdPerMTok": { "in": 3.0, "out": 15.0 }
      },
      "sampleSize": 412,
      "positiveRate": 0.68,
      "confidence": 0.91,
      "mentionsBySource": { "reddit": 210, "x": 120, "hn": 82 },
      "evidence": ["evidence/2026-09-29.jsonl#l1204"],
      "updatedAt": "2026-09-29T00:00:00Z"
    }
  ]
}
```

`data/evidence/YYYY-MM-DD.jsonl`（每行一則）

```jsonc
{
  "hash": "…",                 // 去重鍵
  "modelId": "anthropic/claude-sonnet-4",
  "source": "reddit|x|hn|…",
  "url": "…",
  "author": "…",
  "postedAt": "…",
  "text": "…",
  "label": "positive|negative|neutral",
  "prob": 0.87,                // 評分器給的校準機率
  "judge": "laya@<sha>"
}
```

### Schema v1 實作裁定（A2，2026-09-29；`jason-lab` 以本节為準）

實作見 `src/arena/schema.py`（pydantic v2，一律 `extra="forbid"`）：

1. **數值範圍**：`score`、`dimensions.quality/speed/price` 為 0～100；
   `positiveRate`、`confidence`、`prob` 為 0～1；`priceUsdPerMTok.{in,out}` ≥ 0；
   `windowDays` ≥ 1；`sampleSize` ≥ 0。
2. **`kind`** 鎖定 `"community-sentiment"`（v1 只有一種；要新增視為 schema 變更）。
3. **`source` 鍵不封列**：維持開放字串集合（`reddit|x|hn|…` 依 plan 原意可擴充）。
4. **`evidence` 參照格式**：`[目錄/]檔名.jsonl#l<行號>`，目錄前綴可選。
5. **`meta.judge.calibrated`**：語意是「已通過 C5 校準」；種子資料必須如實設 `false`。

任何放寬都是 v2 的事，需同步 `jason-lab`。

## 任務拆分

### A1 — 專案骨架與 CLI
- 建 `src/`、`tests/`、`data/`，CLI 入口支援 `fetch-models` / `collect` / `score` / `build` / `validate`
- **驗收**：五個子命令都能執行，尚未實作的部分回傳明確的「未實作」訊息

### A2 — schema 定義與 validate
- 用 pydantic（或 JSON Schema）定義 `scores.json` 與 evidence 格式
- **驗收**：`arena validate` 對合法檔回 0、對缺欄位／型別錯的檔回非 0 並指出位置

### C1 — fetch-models
- 讀 `config/models.yaml`（人工清單）＋ OpenRouter `/api/v1/models`，合併定價與 context length
- **驗收**：重跑兩次結果一致；OpenRouter 掛掉時不影響人工清單部分

### C2 — collect
- 以 `last30days` 技能抓近 30 天社群貼文，落地為 evidence jsonl（含 url／時間／原作者）
- 去重：以正規化後的內容 hash 為鍵
- **驗收**：同一則爆紅轉貼只留一筆；每筆都能用 url 連回原文

### C3 — score
- 慢層：rubric 定義（品質／速度／價格）
- 快層：JEV 逐則分類 + 校準機率
- **驗收**：對固定輸入集重跑，分數變動在容許範圍內（可重現）

### C4 — build
- 由 evidence 聚合出 `scores.json`；**分數由公式計算**，不呼叫模型直接打分
- **驗收**：`arena build` 產出的檔案通過 `arena validate`；抽樣 20 筆可從分數連回原始貼文

### C5 — 校準驗證（上線門檻）
- 人工標註 100~200 則，計算準確率與校準曲線
- **驗收**：準確率與校準度達標並記錄在 `docs/research/jev-scoring.md`

## 技術選型

| 項目 | 選擇 | 理由 |
| --- | --- | --- |
| 語言 | Python | JEV 家族（`laya`、`AgentJev`、`LLM2Jev`）皆為 Python／HF transformers |
| HTTP | `httpx` | 簡潔、支援 async |
| 驗證 | `pydantic` | schema 即文件，錯誤訊息清楚 |
| 測試 | `pytest` | 標準選擇 |
| 推論 | 本地跑 `laya`／`AgentJev-0.6B` | 量大、成本近零；避免用 router 做量產評分 |

## 待決事項

- [ ] JEV 具體選用：自架 `laya` 或 `AgentJev-0.6B`／`LLM2Jev`
- [ ] 三個維度的權重與公式定案
- [ ] 社群來源清單（哪些 subreddit／論壇值得抓）
- [ ] 排程頻率（每日或每週）
