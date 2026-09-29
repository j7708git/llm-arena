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
  "url": "…",                  // 永久連結（R3 確認可取得）
  "author": "…" | null,        // 允許 null（R3：last30days 結果常缺作者）
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
6. **`evidence.author` 允許 `null`**（R3 發現，2026-09-29）：`last30days` 的 agent JSON 無
   `author` 欄、raw profile 也只有部分有。此欄改為 `str | None` 屬於放寬，
   在 `jason-lab` 尚未開工前完成，不算破壞契約；站方顯示時以「未知作者」處理。
7. **`evidence.label`／`prob`／`judge` 允許 `null`**（PM 裁定 2026-09-29）：C2 落地的是
   **未評分**貼文，三欄由 C3 回填。`arena validate` 對「結構合法但尚未評分」的 evidence
   檔必須回 0；`scores.json` 的 `meta` 欄位維持必填不變。此變更同樣屬放寬、jason-lab 未受影響。

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

- [x] 社群來源清單（R3 定案，見下「收集策略」）
- [ ] 排程頻率（每日或每週）
- [x] JEV 具體選用（R1 定案 2026-09-29）：**`convaiinnovations/laya` 英文 checkpoint**，
      pin revision `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`，`choice` 題型三類態度，
      校準機率用 `answer_confidence`。詳見 `docs/research/jev-scoring.md`。
- [ ] 三個維度的權重與公式定案（C3/C4 階段，慢層 rubric 後定）

## 收集策略（R3 定案，2026-09-29；C2/C5 依此實作）

來源僅 Reddit + Hacker News（零設定下 `last30days` 對模型評比題的實際覆蓋）：

1. **主收集器**：`last30days` 引擎（`mvanhorn/last30days-skill`，Python ≥3.12），
   用 `--emit=json --json-profile=agent`（v1.3 穩定契約）發現貼文；放大樣本用 `--deep`。
2. **補缺**：`author` 與 HN 討論頁連結用公開 API 回填——
   Reddit `.../comments/<id>/.json`、HN Algolia `hn.algolia.com/api/v1`（皆免 key）。
3. **過濾**：`jobs` 等雜訊來源以 `source` 白名單（reddit／hn）排除；
   `source_status` 只有 `no-results` 可視為「沒討論」，`rate-limited` 等必須退避重試。
4. **偏誤標示**：`meta.windowDays`/`notes` 明示 30 天窗口偏袒新模型；
   低樣本（<20）標「僅供參考」；呈現加「涵蓋來源：Reddit／HN」徽章。
5. **去重**：正規化內容 hash 為鍵（含跨來源轉貼）。

詳見 `docs/research/last30days-skill.md`（坑清單在該檔第 169 行起）。
