# OpenRouter 模型清單 API（`/api/v1/models`）

> 研究日期：2026-09-29（實際 curl 於 2026-09-28 23:36 UTC）
> 用途：C1 `fetch-models` 要從 OpenRouter 取得定價與 context length；本檔確認
> 「哪些 schema 欄位能自動取得、哪些必須人工維護」。
> 原始輸出保留在 `/tmp/opencode/llm-arena-r2/`（`models.json`、`headers.txt`、`providers.json` 等）。

## TL;DR（結論與選型建議，3 句內）

1. `GET https://openrouter.ai/api/v1/models` **公開、免 API key、免認證**，回傳 `{data, total_count, links}`，預設只給「輸出為 text」的模型（本次 460 個）；回應被 Cloudflare 邊緣快取（`cache-control: public, max-age=120`），重跑結果順序一致。
2. 定價是 **USD／每 token 的字串**，`pricing.prompt` → 輸入、`pricing.completion` → 輸出，換成 schema 的 `priceUsdPerMTok` 只要 **× 1_000_000**；`-1` 代表動態/router 定價（不是真價格），必須擋掉。
3. 能自動取得的只有：`id`、`name`（需去掉 `"Provider: "` 前綴）、`pricing.*`、`context_length`、`canonical_slug` 等；`provider` 沒有直接欄位、`score`／`dimensions`／`sampleSize`／`evidence` 等一律**人工／管線維護**。

## 選型細節（版本、理由、替代方案對比）

### 端點清單（實測結果）

| 端點 | 需要 key？ | 實測 | 用途 |
| --- | --- | --- | --- |
| `GET /api/v1/models` | ❌ 免 key（HTTP 200） | 460 筆（預設 text） | **主用**：模型清單＋定價 |
| `GET /api/v1/models?output_modalities=all` | ❌ | 631 筆 | 含 image/embeddings/video… 的完整目錄 |
| `GET /api/v1/models?limit=&offset=` | ❌ | 分頁，預設不給 `limit` 時回全部 | 需要分頁才用 |
| `GET /api/v1/models/count` | ❌ | `{"data":{"count":460}}` | 只需數量時 |
| `GET /api/v1/model/{author}/{slug}` | ❌ | HTTP 200，`{data:{...Model}}` | **單一模型查詢**（注意是單數 `model`，用 `/models/...` 會 404） |
| `GET /api/v1/providers` | ❌ | 111 筆 hosting provider | 服務商清單（**不是**模型作者清單，見坑） |
| `GET /api/v1/benchmarks` | ✅ 需 key（未帶回 401） | — | Anthropic/Design Arena/OpenRouter 基準分數（30 rpm、500/day） |
| `GET /api/v1/datasets/rankings-daily` | ✅ 需 key | — | 每日 top-50 模型 token 用量（排行榜類資料） |
| `GET /api/v1/models?use_rss=true` | ❌ | RSS XML | 訂閱新模型上架 |

- OpenAPI 規格（可直接餵 codegen）：`https://openrouter.ai/openapi.json` / `openapi.yaml`。
- 完整 API 索引（給未來檢索用）：`https://openrouter.ai/docs/llms.txt`。

### 為什麼直接抓 `/models` 就好

- 一次回應約 750 KB、460 筆，涵蓋我們要的定價與 context length，不需要逐模型打單一查詢。
- 邊緣快取 120 秒，且我們每天只抓一次，對對方壓力極小。
- 替代方案：`/v1/models/{author}/{slug}/endpoints` 可拿到「各 hosting provider 各自的定價」，但我們的 schema 只要一個代表價，用 `/models` 的 top-level `pricing` 即可，不必多打。

### `id` 格式（實測）

- 格式為 `<author-slug>/<model-slug>`，例如 `anthropic/claude-sonnet-4`、`openai/gpt-4o`、`deepseek/deepseek-chat`、`z-ai/glm-5.3-prime`；author slug 可能含連字號（`z-ai`、`x-ai`、`meta-llama`、`aion-labs`）。
- **有變體後綴**：`:free`（16 個）、`:batch`（73 個），例如 `openai/gpt-6-sol:batch`、`qwen/qwen3.8-27b:free`。
- **有 `~` 開頭的 alias**（18 個），例如 `~openai/gpt-astra-latest`、`~z-ai/glm-latest`（對應 `alias_target`）。
- 抓清單時應**排除含 `~` 的 alias 與含 `:` 的變體**，否則同一模型會重複計價；`canonical_slug` 是穩定不變的永久 slug。
- 本次 460 筆 default（text）回應中有 64 個不同 author slug。

### 定價單位（重點，官方明載）

- 官方 Models API 文件原文：`pricing` 的「All pricing values are in USD per token/request/unit」，且 OpenAPI schema 對 `PublicPricing.prompt` / `.completion` 的定義是
  `Price in USD per token for prompt (input) processing` / `... completion (output) generation`。
- 同一份文件的 query 參數又佐證了換算：`min_price` / `max_price` 的說明是 **`Minimum/Maximum prompt price in $/M tokens`**。
- 所以：`priceUsdPerMTok.in = float(pricing.prompt) * 1_000_000`、`.out = float(pricing.completion) * 1_000_000`。
- 實測對照（乘完剛好是好記的數）：

  | id | `pricing.prompt` | `pricing.completion` | → in $/MTok | → out $/MTok |
  | --- | --- | --- | --- | --- |
  | `anthropic/claude-sonnet-4` | `"0.000003"` | `"0.000015"` | 3 | 15 |
  | `openai/gpt-4o` | `"0.0000025"` | `"0.00001"` | 2.5 | 10 |
  | `deepseek/deepseek-chat` | `"0.0000002574"` | `"0.0000010287"` | 0.2574 | 1.0287 |

- 其他 pricing key（選用）：`input_cache_read`、`input_cache_write`、`input_cache_write_1h`、`web_search`、`audio`、`image`、`image_output`、`internal_reasoning`、`request`（本次 460 筆中 0 筆有 `request`）、`discount`、`overrides`。
- `overrides`（本次 76 筆有）：長 context 或分時段（peak/off-peak）的條件式定價；**top-level 值代表預設條件的價格**。畫面上用 top-level 即可，但要知道超過門檻會更貴。

## 欄位對照表（schema v1 `models[]` ← OpenRouter）

| schema v1 欄位 | OpenRouter 來源 | 取得方式 | 備註 |
| --- | --- | --- | --- |
| `id` | `data[].id` | ✅ 自動 | 建議以 `canonical_slug` 為穩定鍵；排除 `~` alias 與 `:free`/`:batch` 變體 |
| `name` | `data[].name` | 🟡 半自動 | API 值形如 `"Anthropic: Claude Sonnet 4"`，schema 要的是短名 `"Claude Sonnet 4"` → 需去掉 `"<provider>: "` 前綴；17 筆（如 `stealth/space-bunny-alpha`、`openrouter/auto`）沒有前綴，需人工 |
| `provider` | 無獨立欄位 | 🟡 半自動 | 主來源＝`name` 的 `"Provider: "` 前綴；API 沒有 model-author 欄位。`/api/v1/providers` 是 hosting provider，**不能當作者清單**（google/meta-llama/qwen/x-ai 等不在其中）→ 需人工 alias 對照表 |
| `score` | — | ❌ 人手／build 計算 | 由 C4 公式算出 |
| `dimensions.quality` | — | ❌ 人手／計算 | rubric，非 API |
| `dimensions.speed` | — | ❌ 人手／計算 | rubric，非 API |
| `dimensions.price` | — | ❌ 人手／計算 | CP 值分數，非 API |
| `dimensions.priceUsdPerMTok.in` | `pricing.prompt` | ✅ 自動 | **× 1e6**；字串轉 float；`-1` 要排除 |
| `dimensions.priceUsdPerMTok.out` | `pricing.completion` | ✅ 自動 | **× 1e6**；同上 |
| `sampleSize` | — | ❌ 人手／管線 | 來自 evidence 聚合 |
| `positiveRate` | — | ❌ 人手／管線 | 來自 evidence 聚合 |
| `confidence` | — | ❌ 人手／管線 | 校準結果 |
| `mentionsBySource` | — | ❌ 人手／管線 | 來自 evidence 聚合 |
| `evidence` | — | ❌ 人手／管線 | 指向 evidence jsonl |
| `updatedAt` | — | ❌ 管線產出 | 用抓取時間，不是 API 欄位 |

### 額外可一併抓、但 schema 目前沒有的欄位（C1 可考慮保留）

| OpenRouter 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `canonical_slug` | string | 永久不變的 slug，適合當去重／對應鍵 |
| `context_length` | int | 任務 C1 指定要合併的 context length（本次 460 筆皆為整數、無 null） |
| `created` | int (unix) | 上架時間 |
| `architecture.input_modalities` / `output_modalities` | string[] | 例如 `text+image+file->text` |
| `architecture.tokenizer` | string | `GPT` / `Claude` / `Gemini` / `Qwen3` / `Other`… |
| `top_provider.context_length` / `max_completion_tokens` / `is_moderated` | — | top provider 的服務限制（**注意不是模型作者**） |
| `supported_parameters` | string[] | 例如 `tools`、`reasoning`、`structured_outputs` |
| `expiration_date` / `knowledge_cutoff` | string\|null | 本次 snapshot 多為 null |
| `benchmarks.design_arena[]` | — | 部分模型的 arena ELO（第四方資料，非我們的分數） |

### 必須人工維護的欄位清單（無法從 API 取得）

- `score`
- `dimensions.quality`、`dimensions.speed`、`dimensions.price`（三個維度分數）
- `sampleSize`、`positiveRate`、`confidence`、`mentionsBySource`、`evidence`、`updatedAt`
- `meta` 全部（`schemaVersion`、`generatedAt`、`windowDays`、`kind`、`disclaimer`、`judge`、`notes`）
- `provider` 的「顯示名」對照表（作者 slug → 顯示名，例如 `z-ai` → `Z.AI`）
- `name` 的短名（對沒有 `"Provider: "` 前綴、或想改寫標題的模型）
- `config/models.yaml`「哪些模型值得追」的人工清單本身
- 若模型根本不在 OpenRouter（例如自架的 `laya`）→ 全部欄位人手

## 最小可用範例（可直接參考的代碼片段／指令）

### 實際 curl（本次驗證用）

```bash
mkdir -p /tmp/opencode/llm-arena-r2
curl -sS https://openrouter.ai/api/v1/models -o /tmp/opencode/llm-arena-r2/models.json
# 檢查 HTTP 狀態與快取標頭
curl -sSI https://openrouter.ai/api/v1/models | grep -iE 'HTTP/|cache-control|age|content-type'
```

### 精簡輸出範例（真實回應節錄，未經修改欄位）

```jsonc
{
  "total_count": 460,
  "links": { "next": null },
  "data": [
    {
      "id": "anthropic/claude-sonnet-4",
      "canonical_slug": "anthropic/claude-4-sonnet-20250522",
      "name": "Anthropic: Claude Sonnet 4",
      "created": 1747930371,
      "context_length": 200000,
      "pricing": {
        "prompt": "0.000003",
        "completion": "0.000015",
        "input_cache_read": "0.0000003",
        "input_cache_write": "0.00000375",
        "overrides": [
          { "min_prompt_tokens": 200000, "prompt": "0.000006", "completion": "0.0000225" }
        ]
      },
      "top_provider": { "context_length": 200000, "max_completion_tokens": 64000, "is_moderated": true },
      "architecture": { "modality": "text+image+file->text", "output_modalities": ["text"], "tokenizer": "Claude" }
    }
  ]
}
```

### Python（httpx，符合計畫技術選型）

```python
import httpx

MODELS_URL = "https://openrouter.ai/api/v1/models"

def fetch_models(client: httpx.Client) -> dict[str, dict]:
    """回傳 {id: model}；失敗回空 dict，讓人工清單仍可運作（C1 驗收）。"""
    try:
        r = client.get(MODELS_URL, params={"output_modalities": "text"}, timeout=15)
        r.raise_for_status()
        rows = r.json()["data"]
    except (httpx.HTTPError, KeyError, ValueError):
        return {}

    out: dict[str, dict] = {}
    for m in rows:
        mid = m["id"]
        # 排除 alias（~）與變體（:free / :batch），避免重複與假價格
        if mid.startswith("~") or ":" in mid:
            continue
        out[mid] = m
    return out

def to_mtok(model: dict) -> dict[str, float | None]:
    """pricing 是 USD/token 字串；-1 代表動態定價，視為 None。"""
    def conv(key: str) -> float | None:
        raw = model.get("pricing", {}).get(key)
        if raw is None:
            return None
        v = float(raw)
        return None if v < 0 else v * 1_000_000
    return {"in": conv("prompt"), "out": conv("completion")}
```

### 呼叫建議（快取／失敗處理，對應 C1 驗收）

- **有條件抓取（ETag／時間）**：回應有 `cache-control: public, max-age=120`、`age`，但**沒有 `ETag`／`Last-Modified`**（實測 `HEAD`）。所以無法用 `If-None-Match`；改用「上次抓取時間 < 24h 就跳過」的自建快取。
- **落盤快取**：把原始 `models.json` 存到 `data/cache/openrouter-YYYY-MM-DD.json`（或 `.scratch/`），每次 build 先讀快取，抓不到才用舊的。
- **失敗處理**：網路錯誤／非 2xx／JSON 解析失敗 → **不要讓整條管線失敗**，回傳已抓到的人工清單部分（C1 驗收：「OpenRouter 掛掉時不影響人工清單部分」）。可用指數退避重試 2~3 次再放棄。
- **確定性**：連抓兩次 460 筆，`id` 集合與**順序完全一致**（實測 `same order: True`），適合做 diff 偵測新增／下架。
- **保守頻率**：官方沒有針對 `/models` 公告數字 rate limit（公開限制只涵蓋推論類：free 變體 20 rpm、50~1000 rpd，以及 Cloudflare DDoS 防護）。我們每天抓一次、且回應已邊緣快取，遠低於任何風險門檻。需 key 的 `/benchmarks`、`/datasets/*` 則限 30 rpm、500/day per account。
- **更新頻率**：官方沒有固定排程，說法是「as soon as we confirm it」；`max-age=120` 秒，另提供 RSS（`?use_rss=true`）通知新模型。我們每日一次即可。

## 已知坑與注意事項

1. **單位陷阱**：`pricing.*` 是 **per token**，不是 per MTok，也不是 per 1K token。務必 ×1e6；型別是**字串**（要 `float()`）。
2. **`-1` 不是價格**：動態／router 模型（`typesafe/jev-router`、`openrouter/auto`、`openrouter/pareto-code`…）的 prompt/completion 是 `"-1"`，直接乘會得到負數；必須視為「無固定價」跳過。`"0"` 才是免費。
3. **`provider` 不是 API 欄位**：schema 的 `provider` 要自己推。最可靠的來源是 `name` 的 `"Provider: "` 前綴；`top_provider` 是「服務供應商」不是「模型出品組織」，別誤用。`/api/v1/providers` 是 hosting provider 清單，作者 slug（`google`、`meta-llama`、`qwen`、`x-ai` 等）大多不在裡面，別當對照表用。
4. **預設只回 text 模型**：不帶參數回 460 筆；要全部（含 image/embeddings/video/audio/rerank/decisions）要 `output_modalities=all`（631 筆）。我們的排行榜是文字模型，預設即可。
5. **清單有 noise**：`~author/...-latest` alias（18 筆）與 `:free`／`:batch` 變體（89 筆）都要排除，否則同模型重複、或抓到 `:free` 的 0 價。
6. **`overrides` 會讓實際帳單不同**：top-level 價是預設條件；長 context（`min_prompt_tokens`）或尖峰時段可能更貴。若只顯示單一價，建議註明「一般情境」。
7. **`= -1` 之外的細節**：`pricing.overrides` 內含未知條件欄位時，官方建議「跳過該條而不是套用它的價格」。
8. **單一模型端點是單數**：`/api/v1/model/{author}/{slug}` 才對；`/api/v1/models/{author}/{slug}` 會 404（實測）。
9. **需要 key 的端點會回 401**：`/benchmarks`、`/datasets/rankings-daily` 未帶 key 回 `{"error":{"message":"No cookie auth credentials found","code":401}}`；`/models` 不受影響。
10. **CORS 友善**：`/models` 回 `access-control-allow-origin: *`，瀏覽器端也能直接打（但我們在 CLI 打，不受影響）。

## 來源（連結 + 查詢日期）

- `GET https://openrouter.ai/api/v1/models` 實測回應（儲存於 `/tmp/opencode/llm-arena-r2/models.json`）— 2026-09-28/29
- `GET https://openrouter.ai/api/v1/models/count`、`/api/v1/model/openai/gpt-4o`、`/api/v1/providers`、`?output_modalities=all`、`?use_rss=true` 實測 — 2026-09-29
- `GET https://openrouter.ai/api/v1/benchmarks`、`/api/v1/datasets/rankings-daily` 未帶 key 實測（401）— 2026-09-29
- OpenRouter Docs — Models 指南：<https://openrouter.ai/docs/guides/overview/models> — 2026-09-29
- OpenRouter Docs — List all models（OpenAPI，`PublicPricing` / query params 定義）：<https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties> — 2026-09-29
- OpenRouter Docs — Limits（rate limit、free 變體 RPM/RPD）：<https://openrouter.ai/docs/api-reference/limits> — 2026-09-29
- OpenRouter Docs — List Benchmarks（30 rpm / 500 rpd）：<https://openrouter.ai/docs/api/api-reference/benchmarks/list-benchmarks> — 2026-09-29
- OpenRouter Docs — Daily token totals for top 50 models：<https://openrouter.ai/docs/api/api-reference/datasets/daily-token-totals-for-top-50-models> — 2026-09-29
- OpenRouter OpenAPI 規格：<https://openrouter.ai/openapi.json>（文件索引：<https://openrouter.ai/docs/llms.txt>）— 2026-09-29
