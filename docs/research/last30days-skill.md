# last30days 技能：抓取能力研究

> 研究日期：2026-09-29（實際抓取於 2026-09-28 23:40～23:44 UTC）
> 用途：C2 `collect` 要決定「用 `last30days` 抓近 30 天社群貼文，能拿到哪些來源、能不能取得永久連結、樣本量夠不夠」。
> 技能來源：`mvanhorn/last30days-skill`（MIT，第三方技能，**非本機既有**）。
> 原始抓取輸出保留在 `/tmp/opencode/llm-arena-r3/`（`runs/*.json`、`runs/*.err`）。

## TL;DR（結論與選型建議，3 句內）

1. `last30days` 是一個**第三方 agent skill**（`mvanhorn/last30days-skill`，v3.25.0），本機**沒有安裝**；它靠一支 Python 3.12+ 引擎腳本 `last30days.py` 抓取，**零設定即可用 Reddit + Hacker News + Polymarket + GitHub**，其餘來源（X／YouTube／TikTok／Instagram／部落格網頁…）都需要 API key 或外部 CLI。
2. 實際抓 3 個模型名稱（quick 模式、預設 30 天窗口）：每筆都拿得到 `url`（**100% 有永久連結**）、`published_at`、`title`、`summary`、`engagement`；但主要來源只有 **Reddit 6 筆 + HN 0～6 筆**（外加雜訊很大的 jobs 結果），**樣本量偏小**，且 **agent JSON 沒有 `author` 欄位**。
3. **建議**：可用，但 C2 必須把它當「Reddit + HN 的抓取器」而非全能來源；抓取用 `--emit=json --json-profile=raw`（拿得到 `author`／`top_comments`）、需要放大樣本時用 `--deep`，並在 `scores.json.meta` 明示「僅涵蓋 Reddit／HN、近 30 天窗口會偏袒新模型」。

## 技能身分與可用性（最重要的事實）

| 項目 | 實測結果 |
| --- | --- |
| 是否為本機既有技能 | **否**。`~/.config/opencode/skills/`、`~/.agents/skills/`、`~/.claude/skills/`、工作區內皆無 `last30days`（`find`／`grep` 於 2026-09-29 全數落空） |
| 實際來源 | `https://github.com/mvanhorn/last30days-skill`，授權 MIT，v3.25.0（commit `084662b`，2026-09-22） |
| 安裝方式（供後續採用） | `npx skills add mvanhorn/last30days-skill -g`（官方 README 明確列出支援 `opencode` harness）；或 Claude Code 用 `/plugin marketplace add` |
| 引擎入口 | `skills/last30days/scripts/last30days.py`（單檔約 184 KB），執行需 **Python 3.12+** |
| 本機 Python | 系統 `python3` 為 3.10.12，**太舊**；改用 uv 內建的 3.12.14 才跑得動（`/home/jason/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12`） |
| 憑證現況 | **全部未設定**：`OPENAI_API_KEY`、`XAI_API_KEY`、`SCRAPECREATORS_API_KEY`、`BRAVE_API_KEY`… 皆 unset；`gh` CLI 已登入（GitHub 來源可用） |
| 設定檔位置 | `~/.config/last30days/.env`（本機不存在） |

> 結論：技能本身**在本機不可直接以 `/last30days` 叫用**；本研究是 clone 原始 repo 後直接跑引擎，驗證它「實際抓得到什麼」。這也代表 C2 若要用，必須先安裝或 vendor 這支引擎。

## 支援來源與覆蓋率

### 零設定可用（`--diagnose` 實測）

```
available_sources: [reddit, hackernews, polymarket, github, grounding]
```

| 來源 | 零設定可用？ | 本次是否抓到資料 | 備註 |
| --- | --- | --- | --- |
| Reddit（含留言） | ✅ | ✅ 每題 6 筆 | keyless RSS + shreddit 爬取 + arctic-shift 補分數，**有真實 upvote／留言數** |
| Hacker News | ✅ | ✅ 部分題目 6 筆 | 走 Algolia API；`url` 常指向**外部原文**，非 HN 討論頁 |
| Polymarket | ✅ | ❌ 0 筆 | 只有題目是事件／預測市場時才有；模型評比題抓不到 |
| GitHub | ✅ | ❌ 0 筆 | 需要 `gh`（已登入）；只有「人／repo」型題目才會有 |
| grounding（網頁／部落格） | ⚠️ 名義上可用，實際 **0 筆** | ❌ | **沒有 Brave／Exa／Serper key 時 keyless 後端回 `no-results`**（見下方實測） |
| jobs（求職） | ✅（自動附加） | ⚠️ 有，但雜訊大 | LinkedIn 職缺頁、廣告轉址，**對模型態度幾乎無訊號**，建議 C2 直接過濾掉 |

### 需要額外憑證／工具才有的來源

| 來源 | 需要什麼 | 本機現況 |
| --- | --- | --- |
| X / Twitter | 瀏覽器 cookie（`AUTH_TOKEN` + `CT0`）或 `XAI_API_KEY` | 未設定 → X 完全跳過 |
| YouTube（含逐字稿） | `yt-dlp` | 未安裝 |
| TikTok / Instagram / Threads / Pinterest | `SCRAPECREATORS_API_KEY`（免費額度 10,000 次） | 未設定 |
| arXiv / Techmeme / Digg | 對應免費 CLI（`arxiv-pp-cli` 等，首次設定會自動裝） | 未安裝 |
| Bluesky | `BSKY_HANDLE` + `BSKY_APP_PASSWORD` | 未設定 |
| LinkedIn / Meta Ads / StockTwits / Trustpilot / Amazon / Telegram | 各自 opt-in 設定 | 未設定 |

> 覆蓋率結論：在**本機零設定的真實狀態**下，`last30days` 對「LLM 模型評比」這類題目，實質上只等於 **Reddit + Hacker News**（外加要過濾掉的 jobs）。

## 實際抓取結果（不是「應該可以」）

執行方式（quick 模式、預設 30 天窗口、agent JSON profile）：

```bash
PY=/home/jason/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12
$PY skills/last30days/scripts/last30days.py "<模型名>" --quick --emit=json \
    --json-profile=agent --output runs/<slug>.json
```

| 查詢字串 | 總筆數 | 來源分佈 | `source_status` |
| --- | --- | --- | --- |
| `Claude Sonnet 4` | 9 | reddit 6、jobs 3 | reddit=ok、hackernews=no-results、jobs=ok、grounding=no-results |
| `GPT-5` | 15 | reddit 6、hackernews 6、jobs 3 | reddit=ok、hackernews=ok、jobs=ok、grounding=no-results |
| `Gemini 2.5 Pro` | 12 | reddit 6、hackernews 6 | reddit=ok、hackernews=ok、jobs=unreachable、grounding=no-results |
| `GPT-5`（`--days 7` 對照組） | 9 | hackernews 6、jobs 3 | **reddit=rate-limited**、hackernews=ok |

補充實測：

- **永久連結**：三題結果的 `url` 覆蓋率皆為 **9/9、15/15、12/12＝100%**。Reddit 為 `https://www.reddit.com/r/<sub>/comments/<id>/<slug>/` 的永久連結；HN 為外部原文或 `news.ycombinator.com/item?id=...`。
- **時間**：`published_at` 在 30 天窗口內（例：`2026-09-25`、`2026-09-27`），reddit 幾乎全有、jobs 缺。
- **互動數**：Reddit 有 `engagement.score`／`num_comments`（例：score 3914、456 留言）；HN 有 `points`／`comments`。
- **rate limit 真實存在**：連續第 5 次 keyless Reddit 抓取時回報 `reddit=rate-limited`（同一時段 HN 仍正常），證明 keyless Reddit 路徑會被打限。
- **grounding 明確為空**：單獨 `--search grounding --web-backend keyless` 抓 `LLM leaderboard`，回傳 `results: []`、`grounding: no-results` → **沒有搜尋 API key 就抓不到部落格／網頁**。

## 回傳格式（agent JSON profile v1.3）

```jsonc
{
  "schema_version": "1.3",
  "query": "GPT-5",
  "generated_at": "2026-09-28T23:40:57Z",
  "window_days": 30,                 // 時間窗口天數（可調，見下）
  "source_status": { "reddit": "ok", "hackernews": "ok", "jobs": "ok", "grounding": "no-results" },
  "clusters": [ { "title": "...", "summary": "...", "sources": ["reddit"], "engagement_total": 3914 } ],
  "results": [
    {
      "candidate_id": "https://reddit.com/r/OpenAI/comments/1wnq2cb/...",
      "title": "Sir, Dario just dropped opus 5.5 ...",
      "source": "reddit",                 // reddit | hackernews | jobs | polymarket | github | grounding | ...
      "url": "https://www.reddit.com/r/OpenAI/comments/1wnq2cb/...",  // 永久連結
      "published_at": "2026-09-22",
      "summary": "Pacing the frontier ...",// 貼文摘要（reddit 常含留言彙整）
      "engagement": { "score": 3914, "num_comments": 456 },
      "relevance_score": 0.4718,           // 0.0–1.0
      "cluster": 1
    }
  ]
}
```

`source_status` 的狀態值很重要（文件定義）：`ok`／`no-results`／`partial`／`rate-limited`／`auth-failed`／`payment-required`／`unreachable`／`timeout`／`schema-drift`／`skipped-unconfigured`／`error`。
**只有 `no-results` 代表「乾淨地查無資料」**；其餘失敗狀態不能當成「沒有討論」。

### 關於 `author`（重要缺口）

- **agent profile 沒有 `author` 欄位**。C2 的 evidence schema 需要 `author`，這點必須自己補。
- `--json-profile=raw`（未版本化、可能變動）的 `source_items[].author` **部分有值**：本題 raw 檔 9 個 source item 只有 3 個有 `author`（jobs 填 `"web"`），**Reddit 貼文本身的 `author` 仍常缺**。
- Reddit **留言**作者拿得到：raw 的 `metadata.top_comments[].author` **72/72 都有**，且帶 `url`（可作 comment permalink）。
- Reddit 貼文作者有時只藏在 `summary` 的 `submitted by /u/<name>` 字串裡（本次 12 個 reddit item 只有 2 個含 `/u/`）。
- 可行補法：`author` 設為 nullable；或另外用 Reddit 公開 JSON `https://www.reddit.com/r/<sub>/comments/<id>/.json` 的 `author` 欄補齊。

## 時間窗口：不是固定 30 天，可調

- **預設 30 天**（程式碼 `lookback_days or 30`，輸出 `window_days: 30`）。
- CLI 有 `--days N`／`--lookback-days N` 可改（實測 `--days 7` → 輸出 `window_days: 7`，且 HN 命中數不變、Reddit 被打限）。
- 另有 `--as-of YYYY-MM-DD` 可做「歷史時點」回看。
- 每筆結果的 `published_at` 落在 `[range_from, range_to]` 內（raw 檔可見 `range_from=2026-08-29`、`range_to=2026-09-28`）。

## 最小可用範例

```bash
# 1) 安裝（支援 opencode harness；-g 裝到使用者層級）
npx skills add mvanhorn/last30days-skill -g

# 2) 若系統 Python < 3.12，用 uv 取一個 3.12（本機已具備）
PY=/home/jason/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12

# 3) 看目前哪些來源可用（零設定＝reddit/hackernews/polymarket/github/grounding）
$PY skills/last30days/scripts/last30days.py --diagnose

# 4) 抓一個模型名稱，輸出可程式處理的 JSON（C2 建議用 raw 以取得 author/top_comments）
$PY skills/last30days/scripts/last30days.py "Claude Sonnet 4" \
    --emit=json --json-profile=raw --deep \
    --output /tmp/opencode/llm-arena-r3/claude-sonnet-4.json

# 5) 只要 agent 契約（穩定、版本化 v1.3）時：
$PY skills/last30days/scripts/last30days.py "GPT-5" --emit=json --json-profile=agent \
    --output /tmp/opencode/llm-arena-r3/gpt-5.json

# 6) 放寬/縮窄窗口、指定來源
$PY skills/last30days/scripts/last30days.py "Gemini 2.5 Pro" --days 60 --search reddit,hackernews --emit=json
```

從 JSON 取 evidence 欄位（Python 示意）：

```python
import json
d = json.load(open("claude-sonnet-4.json"))
for r in d["results"]:
    if r["source"] not in ("reddit", "hackernews"):   # 過濾 jobs 等雜訊來源
        continue
    evidence = {
        "source": "hn" if r["source"] == "hackernews" else r["source"],
        "url": r.get("url"),                          # 永久連結，100% 有
        "postedAt": r.get("published_at"),
        "text": r.get("summary") or r.get("title"),
        "author": None,                               # agent profile 無此欄；raw profile 才部分有
    }
```

## 已知坑與注意事項

1. **本機未安裝**：`/last30days` 在本機叫不動；C2 需先 `npx skills add` 或 vendor 引擎，並確保 Python ≥ 3.12。
2. **零設定來源比宣傳少**：README 說 Reddit／HN／Polymarket／GitHub「work immediately」，但對 LLM 評比題，實際只有 **Reddit + HN** 有料；**網頁／部落格（grounding）沒有搜尋 key 就是空的**。
3. **樣本量小**：quick 模式每題只回 ~6 筆 Reddit，對「排行榜」而言樣本數偏低；要放大請用 `--deep`（預設請求 30–50、deep 70–100）。仍受 Reddit keyless 上限影響。
4. **Reddit 會被限流**：連續抓取後出現 `reddit=rate-limited`；排程需加退避與重試，且不可把 `rate-limited` 當成「沒討論」。
5. **jobs 是雜訊**：會混入 LinkedIn 職缺頁、DuckDuckGo 廣告轉址（`relevance_score` 低到 0.067），C2 應以 `source` 白名單只留 `reddit`／`hackernews`（未來可加 `x`／`youtube`）。
6. **HN 沒有討論頁永久連結**：`url` 多為外部原文，agent JSON 無 HN `item?id` 討論連結欄位；若要「連回 HN 討論」需自行補 Algolia 查詢。
7. **agent profile 無 `author`**：需用 `--json-profile=raw`（未版本化）或另外打 Reddit JSON 補齊；schema 的 `author` 建議允許 null。
8. **agent 契約 v1.3 穩定、raw 不穩定**：若直接依賴 JSON 欄位，優先用 `--json-profile=agent`；但 `author` 只有 raw 有——這是取捨。
9. **近 30 天窗口偏誤（必須在呈現標示）**：
   - 窗口只算近 30 天，**剛發布／剛洗版的模型聲量會爆高**，成熟但沒新消息的好模型會被低估（本次三題的熱門幾乎都是「最新幾代」的討論）。
   - 呈現做法：`meta.windowDays` + `meta.notes` 明寫「近 30 天窗口，會偏袒近期熱門模型」；每張卡顯示 `sampleSize`、`mentionsBySource`、`updatedAt`；樣本數低於門檻（例如 < 20）時標「低樣本／僅供參考」；另加「資料涵蓋來源」徽章，明示目前只有 Reddit／HN，不是全網。
   - 不要讓分數看起來像 benchmark；維持 `kind: "community-sentiment"` 與 `disclaimer`。
10. **來源清單變動**：`available_sources` 依環境而異，必須以每次執行的 `--diagnose`／`source_status` 為準，不要寫死。

## 替代方案（若不想依賴此技能）

- **Reddit**：公開 JSON（`https://www.reddit.com/r/<sub>/comments/<id>/.json`）＋ `arctic-shift` API（可拿真實分數）；或 Pushshift 系替代。
- **Hacker News**：Algolia API `https://hn.algolia.com/api/v1/search_by_date?query=<model>&numericFilters=created_at_i>...`，**免 key**，回傳 `objectID`、`author`、`points`、`num_comments`、`created_at`、`story_url`——**比 `last30days` 更能直接拿到 HN 討論永久連結與作者**。
- 兩者都能直接對上 evidence schema 的 `url`／`author`／`postedAt`，可作為 `last30days` 的補強或退路。

## 來源（連結 + 查詢日期）

- `mvanhorn/last30days-skill` GitHub repo（README、SKILL.md v3.25.0、`docs/reference/json-export.md`、`docs/how-search-works.md`）：<https://github.com/mvanhorn/last30days-skill>（查詢日期 2026-09-29；clone commit `084662b501fb0dba95bd55eff0c258d35e0dc499`）
- SKILL.md：<https://github.com/mvanhorn/last30days-skill/blob/main/skills/last30days/SKILL.md>（2026-09-29）
- Agent JSON export 契約：<https://github.com/mvanhorn/last30days-skill/blob/main/docs/reference/json-export.md>（2026-09-29）
- 技能說明頁（SkillsCat）：<https://skills.cat/skills/mvanhorn/last30days-skill>（2026-09-29）
- 使用教學（tosea.ai）：<https://tosea.ai/blog/last30days-ai-research-skill-guide>（2026-09-29）
- Hacker News Algolia API：<https://hn.algolia.com/api>（2026-09-29）
- 本機實測輸出：`/tmp/opencode/llm-arena-r3/runs/`（`claude-sonnet-4.json`、`gpt-5.json`、`gemini-2.5-pro.json`、`claude-sonnet-4.raw.json`、`gpt-5-days7.json`、`grounding-keyless.json`）
