# Jason Lab 專案計畫

> 狀態：規劃定案，尚未動工
> 定案日期：2026-09-29

## 1. 一句話目標

建立一個「作品集 + 真的能用的工具」的網站，第一個工具是**模型社群評價排行榜**；
站名是容器，工具是頁面，之後任何新工具都能塞進來而不必改站名。

## 2. 命名與 repo 佈局

| 項目 | 決定 |
| --- | --- |
| 品牌／站名 | **Jason Lab** |
| 域名 | `jasonlab.dev`（候選 `.app` / `.io` / `.works`；`.dev` 為首選） |
| Git owner | `j7708git` |
| 網站 repo | `github.com/j7708git/jason-lab`（目錄 `agent/jason-lab/`） |
| 工具 repo | `github.com/j7708git/llm-arena`（目錄 `agent/llm-arena/`） |
| 站內子品牌 | 排行榜頁叫 `Lab Arena`（路徑 `/arena`） |

域名查詢結果（2026-09-29，DNS 無紀錄僅代表「很可能」可註冊，下單前需實際確認）：

- `jasonlab.dev` / `.app` / `.io` / `.works`：無 A／NS 紀錄 → 可能可註冊
- `jasonlab.site`：已到期被停放 → 不用
- `jason-lab.dev`（有連字號）：已被 Cloudflare 托管 → 已被註冊

GitHub handle 檢查：`jasonlab`、`jason-lab` 兩個使用者名稱都已被他人註冊（不影響 repo 名，只影響是否想把 handle 換成這個名字）。

## 3. 架構決策

**核心原則：有獨立資料管線、或別人可不靠網站使用 → 獨立 repo；只是一個頁面 → 放站內。**

排行榜兼具兩者，所以拆成：

```
j7708git/llm-arena     ← 工具本體（管線 + 資料產物），可 CLI 重跑
    src/               fetch-models / collect / score / build
    data/scores.json        算好的分數（網站讀這個）
    data/evidence/*.jsonl   原始貼文與引用，可回溯審核
    tests/
    README.md

j7708git/jason-lab     ← 網站外殼（Astro）
    src/pages/index.astro   作品集首頁
    src/pages/arena.astro   排行榜頁（build 時讀 scores.json）
    src/pages/about.astro
    docs/plan.md, docs/research/, docs/architecture.html
```

- **介面 = `data/scores.json` 的 schema**，先冷凍再各自開發。
- **只做一個 UI**：工具 repo 不另做網站，最多提供本機預覽。
- 網站取得資料的方式優先選「已發布的資料產物」（GitHub raw／release／npm），讓兩個 repo 完全解耦，不必跨目錄讀檔。

## 4. 資料契約（schema v1 草案）

`scores.json`

```jsonc
{
  "meta": {
    "schemaVersion": 1,
    "generatedAt": "2026-09-29T00:00:00Z",
    "windowDays": 30,
    "kind": "community-sentiment",          // 明確標示不是 benchmark
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

`evidence/YYYY-MM-DD.jsonl`（每行一則）

```jsonc
{
  "hash": "…",                  // 去重鍵
  "modelId": "anthropic/claude-sonnet-4",
  "source": "reddit|x|hn|…",
  "url": "…",
  "author": "…",
  "postedAt": "…",
  "text": "…",
  "label": "positive|negative|neutral",
  "prob": 0.87,                 // 評分器給的校準機率
  "judge": "laya@<sha>"
}
```

## 5. 資料來源與評分方法

1. **模型清單**：以人工維護的清單為主（只追值得追的），附掛 OpenRouter 公開 API `https://openrouter.ai/api/v1/models` 的定價與 context length；每日抓一次。不要爬 HTML。
2. **社群評價收集**：排程 agent 使用 `last30days` 技能抓近 30 天討論（Reddit／X／HN／論壇）。
3. **評分（兩層設計）**：
   - 慢層（做一次）：用強推理模型＋rubric 定義「品質／速度／價格 CP 值」的判斷準則與邊界案例。
   - 快層（做很多次）：用 JEV 家族對**逐則貼文**分類「對某模型的態度」並輸出校準機率。
     - 推薦自架 `convaiinnovations/laya`（Apache-2.0，text-classification，System One）或 `AgentJev-0.6B`（~50ms、不解碼 output token，成本極低）。
     - `typesafe/jev-router` 是 router 不是量產評分器，不用於此用途。
4. **分數是算出來的，不是模型直接給的**：以「正面提及比例 × 樣本數加權」計算，保留公式可驗證。

### 必須做的驗證（上線門檻）

- **人工標 100~200 則**當 ground truth，檢查準確率與**校準度**（說 0.8 正面時是否真的約 80% 正面）。
- **去重**：同一則爆紅貼文轉貼多次只能算一次（用 `hash`）。
- **避免自我偏袒**：評分器不去評自家家族的答案；送評時遮蔽模型名。

## 6. 儲存策略

| 媒介 | 用途 |
| --- | --- |
| `data/scores.json` | **主力**，網站真正讀的資料，進 git，有 commit history |
| `data/evidence/*.jsonl` | **要**，原始證據，讓分數可回溯審核 |
| Google Sheet | 可選，只給你手動微調用 |
| SQLite | 現在不用 |
| 資料庫（Postgres／D1…） | 只有需要「使用者寫入」（站內投票、留言）時才評估 |

**結論：現在完全不需要 DB。**

## 7. 分階段計畫與驗收條件

### Phase A — 立專案 + 凍結資料契約
- 建 `agent/llm-arena/`、`agent/jason-lab/`，各自 `git init`、`README.md`、`docs/plan.md`、`docs/research/`（`llm-arena` 另需 `docs/architecture.html`）
- 定案 `scores.json` / evidence jsonl 的 schema
- `llm-arena` CLI 骨架：`fetch-models` / `collect` / `score` / `build` / `validate`，先以手寫假資料跑通 `build`
- **驗收**：`arena validate` 能檢查 JSON 符合 schema；`arena build` 從假資料產出合法的 `scores.json`

### Phase B — 薄網站 + 部署
- `jason-lab` 用 Astro + Tailwind；首頁（自我介紹＋作品入口）＋ `/arena` 排行榜頁
- 排行榜頁讀 `scores.json`，支援排序、廠牌篩選、維度切換（品質／速度／價格）、標註樣本數與「非 benchmark」提示
- 沿用 `resume-site` 既有設計 token（暗色、工程文件感、琥珀點綴），不另立一套
- 部署 Cloudflare Pages／GitHub Pages，綁 `jasonlab.dev`
- **驗收**：換一份 `scores.json` 後重建，頁面內容正確更新；線上網址可開

### Phase C — 真 pipeline
- OpenRouter 每日抓模型清單；排程 agent（last30days）抓社群；JEV 逐則評分；輸出 `scores.json` + `evidence/*.jsonl` 並自動 commit
- 完成 100~200 則人工標註與校準驗證
- **驗收**：連續兩天排程自動產出且分數變動可從 git 歷史追溯；抽樣 20 則可從分數連回原始貼文

### Phase D — 收斂
- 磨作品集頁（拿真實排行資料當內容）
- 決定 `resume-site` 是「吸收成 `/resume` 一頁」或「保持獨立並互相連結」
- 可選：把排行榜抽成可嵌入的 Web Component（等有第二個工具再抽象）

## 8. 待決事項

- [ ] `jasonlab.dev` 實際註冊（動手部署前）
- [ ] JEV 具體選用：自架 `laya` 或 `AgentJev-0.6B`／`LLM2Jev`
- [ ] 三個維度的權重與公式定案
- [ ] 排程頻率（每日或每週）
- [ ] 是否合併 `resume-site`（Phase D 再定）

## 9. 風險與注意事項

- **30 天窗口＝近期聲量**，會偏袒剛發布／剛洗版的模型；畫面必須明確標示。
- **分數必須可解釋**：不要叫模型直接吐一個 7.8 分。
- **兩個 repo ＝ 兩份 CI 與依賴**，靠凍結的 schema 與版本化資料產物把摩擦壓到最小。
- **不要過早抽象**：只有一個工具時不要抽共用零件庫。
- **跨目錄權限**：工作區已開放 `$HOME/workspace/agent/*`，但子 session 仍建議把需要的檔案放進自己的專案目錄。
