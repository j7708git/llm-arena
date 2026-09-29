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

## 資料契約（schema v1.1，2026-09-29 修訂）

介面檔案：`data/scores.json`。**v1.1 為定稿**（jason-lab 尚未開工，本次修訂不算破壞契約）；
之後再變更需同步 `jason-lab`。

**v1→v1.1 變化**（依使用者定案：排行榜是 datatable，每欄由 JEV 逐則判斷社群態度後聚合）：

- 維度從固定 3 欄改為**開放 map**，v1.1 初始 5 維＋1 總評；
  網站表格欄位**由 `meta.dimensions` 驅動**，之後加維度（前端/後端/財務適合度…）
  只是管線多問一題、meta 多一筆，站方不用改版。
- evidence 的單筆 `label/prob` 改為 `votes`（各面向的態度判定＋校準機率）。
- 「這則沒談該面向」是 `not-discussed`（不同於「談了但中立」）；`P+N=0` 的維度分是 `null`，
  站方顯示「資料不足」，**不得顯示成 50**。

### scores.json

```jsonc
{
  "meta": {
    "schemaVersion": 1.1,
    "generatedAt": "2026-09-29T00:00:00Z",
    "windowDays": 30,
    "kind": "community-sentiment",              // 明確標示不是 benchmark
    "disclaimer": "社群聲量代理指標，非 benchmark",
    "judge": { "model": "laya", "revision": "<sha>", "calibrated": false },
    "dimensions": [                              // 站方表格欄位的資料來源
      { "id": "quality",         "label": "智能" },
      { "id": "speed",           "label": "速度" },
      { "id": "tokenEfficiency", "label": "Token 效率" },
      { "id": "tokenUsage",      "label": "Token 用量" },
      { "id": "priceValue",      "label": "CP 值" }
    ],
    "weights": { "quality": 0.5, "speed": 0.2, "tokenEfficiency": 0.05,
                 "tokenUsage": 0.05, "priceValue": 0.2 },   // 總分權重，build 讀它
    "sourcesCovered": ["reddit", "hn"],          // 涵蓋徽章（R3 偏誤標示）
    "notes": "近 30 天窗口，會偏袒近期熱門模型"
  },
  "models": [
    {
      "id": "anthropic/claude-sonnet-4",
      "name": "Claude Sonnet 4",
      "provider": "Anthropic",
      "score": 72.4,                             // 總分＝weights 加權（null 維度剔除後重歸一）
      "dimensions": {                            // 鍵 = meta.dimensions[].id，值 0~100 或 null
        "quality": 78.1,
        "speed": 61.0,
        "tokenEfficiency": 66.3,
        "tokenUsage": 40.2,
        "priceValue": 55.3
      },
      "priceUsdPerMTok": { "in": 3.0, "out": 15.0 },   // 硬資料，來自 models.json，非態度
      "dimensionSamples": { "quality": 45, "speed": 12, "tokenEfficiency": 0 },
      "sampleSize": 412,                         // 該模型全部 evidence 筆數
      "positiveRate": 0.68,                      // overall（總評）的正面率
      "confidence": 0.91,
      "mentionsBySource": { "reddit": 210, "hn": 82 },
      "evidence": ["evidence/2026-09-29.jsonl#l1204"],
      "updatedAt": "2026-09-29T00:00:00Z"
    }
  ]
}
```

### evidence/YYYY-MM-DD.jsonl（每行一則）

```jsonc
{
  "hash": "…",                 // 去重鍵
  "modelId": "anthropic/claude-sonnet-4",
  "source": "reddit|x|hn|…",
  "url": "…",                  // 永久連結（R3 確認可取得）
  "author": "…" | null,        // 允許 null（R3：last30days 結果常缺作者）
  "postedAt": "…",
  "text": "…",
  "votes": {                   // 未評分時整個 votes 為 null（C2 落地狀態）
    "overall":          { "label": "positive|negative|neutral", "prob": 0.87 },
    "quality":          { "label": "positive|negative|not-discussed", "prob": 0.81 },
    "speed":            { "label": "…", "prob": 0.66 },
    "tokenEfficiency":  { "label": "…", "prob": 0.55 },
    "tokenUsage":       { "label": "…", "prob": 0.49 },
    "priceValue":       { "label": "…", "prob": 0.90 }
  },
  "judge": "laya@<sha>" | null
}
```

### Schema 實作裁定（v1.1，2026-09-29；`jason-lab` 以本節為準）

實作見 `src/arena/schema.py`（pydantic v2，一律 `extra="forbid"`）：

1. **數值範圍**：`score`、`dimensions.*`（非 null 時）為 0～100；`positiveRate`、
   `confidence`、`votes.*.prob` 為 0～1；`priceUsdPerMTok.{in,out}` ≥ 0（null 允許，
   models.json 查無定價時）；`windowDays` ≥ 1；`sampleSize`/`dimensionSamples.*` ≥ 0；
   `weights` 各值 0～1。
2. **`kind`** 鎖定 `"community-sentiment"`。
3. **`source` 鍵不封列**：開放字串集合。
4. **`evidence` 參照格式**：`[目錄/]檔名.jsonl#l<行號>`，目錄前綴可選。
5. **`meta.judge.calibrated`**：語意是「已通過 C5 校準」；種子與 C5 通過前必須如實 `false`。
6. **`evidence.author` 允許 `null`**（R3 發現）：站方顯示「未知作者」。
7. **未評分狀態合法**：`votes` 與 `judge` 可為 `null`；`arena validate` 對未評分 evidence
   回 0。
8. **維度語意分工**：`overall`（positive/negative/neutral）＝總評；五個面向維度
   （positive/negative/not-discussed）＝逐面向投票。`neutral` 不適用於面向維度，
   `not-discussed` 不適用於 overall。
9. **`dimensions` 的鍵必須是 `meta.dimensions` 宣告過的 id**（validate 要交叉檢查）；
   `tokenEfficiency`（囉嗦與否／上下文利用率）與 `tokenUsage`（完成任務燒多少 token、
   額度消耗）兩欄 v1 先分開；若 C5 發現社群訊號分不開，合併為一欄屬 schema 變更。
10. **總分公式**（C4）：每面向 `n=P+N`；`n=0` → `null`（資料不足）。
    `raw=(P−N)/n`、`dimScore=50×(raw+1)×n/(n+K) + 50×K/(n+K)`（K=10 偽樣本數收縮：
    n=10 收一半、n=90 收 10%，樣本越小越往 50 靠攏；K 寫死在 `build.py` 常數）。
    總分 `score=Σ w_i·dim_i / Σ w_i`（只計非 null 面向），`w` 讀 `meta.weights`
    （預設 quality 0.5／speed 0.2／priceValue 0.2／tokenEfficiency 0.05／tokenUsage 0.05）。
    模型層 `confidence`＝overall 正面率的 Wilson 95% 下界（樣本信任度）。
    `sampleSize=0` 的模型**不入榜**（不出現在 models[]，於 `meta.notes` 交代排除清單）。
    分數全部由公式算出，模型不直接打分。
11. **`data/evidence/` 只放真實蒐集資料**（PM 裁定，2026-09-29）：種子範例移至
    `data/samples/evidence.sample.jsonl`（站方開發/schema 示例用）。score/build 的
    預設 glob 只讀 `data/evidence/*.jsonl`，假資料不得混入聚合與溯源連結。

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

### C3 — score ✅（overall 總評完成；多維度升級見 A3）
- 快層：JEV 逐則分類 + 校準機率（laya、`answer_confidence`，見 `docs/research/jev-scoring.md`）
- **驗收**：對固定輸入集重跑，分數變動在容許範圍內（可重現）——已達（2308e40）

### A3 — schema v1.1 多維度改造（2026-09-29 新增，C4/C5 的前置）
- `schema.py`：evidence 改 `votes` map、scores 改開放 `dimensions`＋`meta.dimensions/weights/sourcesCovered`
- `score.py`：同一次 laya pass 問 6 題（overall＋5 面向），回填 votes
- 種子資料與既有 evidence 依新 shape 重建／重評
- **驗收**：`validate` 過新種子；真跑 score 對 `2026-09-29.jsonl` 全部回填 votes 且校準機率欄位正確；重現性與冪等維持

### C4 — build（依 v1.1）
- 由 evidence 的 `votes` 聚合出 `scores.json`；**分數由公式計算**（裁定第 10 條），不呼叫模型直接打分；
  定价/`priceUsdPerMTok` 自 `data/models.json` 附掛
- **驗收**：`arena build` 產出的檔案通過 `arena validate`；抽樣 20 筆可從分數連回原始貼文；
  全無某面向討論時該維度為 null 且總分正確重歸一

### C5 — 校準驗證（上線門檻）
- 人工標註 100~200 則（**每則標 6 個面向**：overall＋5 維度），計算準確率與校準曲線
- 對 `overall` 與各面向維度分別量 ECE；`not-discussed` 判定單獨切片
- **驗收**：準確率與校準度達標並記錄在 `docs/research/jev-scoring.md`（標註指南 `docs/annotation-guide.md` 先凍結）

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
- [x] 維度與公式定案（v1.1 定稿：5 面向＋總評、逐面向投票聚合，見實作裁定 8~10）

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
6. **歸屬三態（C6 規則）**：text 含 query 模型名→留；不含且含其他清單模型名→丟
   （`misattributed`）；兩者皆無→留（靠引擎 relevance）。2026-09-29 已對舊池回溯同一
   規則：刪除 23/239 筆錯歸屬（Sonnet 4 與 GPT-5 各 11、Gemini 1），Sonnet 4 總分應聲
   下跌 7.5 分——證明模糊比對污染是榜單的頭號品質風險。規則已內建於 collect；
   若直接動手改過 `data/evidence/`（回填、外來資料），重跑 build 前須先以同款
   三態邏輯掃一遍池（可參考本次清洗腳本的做法）。

詳見 `docs/research/last30days-skill.md`（坑清單在該檔第 169 行起）。
