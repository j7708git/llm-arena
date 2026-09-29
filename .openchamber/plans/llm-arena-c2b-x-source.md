# llm-arena · C2b：collect 加入 X/Twitter 來源（使用者提供憑證後才動工）

- 專案：`/home/jason/workspace/agent/llm-arena`
- 要讀：`docs/plan.md`（收集策略、schema v1.1）、`docs/research/last30days-skill.md`
  （X 需 `AUTH_TOKEN`+`CT0` cookie 或 `XAI_API_KEY`）、`src/arena/collect.py`、
  `vendor/last30days/README.md`
- 前置：A3（v1.1 多維度）、C2；**且使用者已在本機放好 X 憑證**
- 動工前確認：`vendor/last30days` 引擎跑 `--diagnose`，`x` 必須出現在可用來源

## 目標

把 X/Twitter 加入收集來源（LLM 社群評價在 X 上的密度高），evidence 的
`source` 增 `x`，`meta.sourcesCovered` 同步。

## 要做的事

- `collect.py`：來源白名單加 `x`；X 貼文欄位對應（永久連結 `https://x.com/<user>/status/<id>`、
  作者、時間）依引擎實際輸出為準（先手動跑一題驗證欄位，不準憑記憶）。
- **沒憑證也要優雅**：引擎回報 `skipped-unconfigured` 時跳過 x、警告但不中斷、
  不影響 reddit/hn（排程可跑）。
- 現有過濾照舊適用：非英文、多模型提及、缺 url/時間、hash 去重。
- 真實抓一輪（2~3 個模型）並 `arena score` 重評新增筆，端到端 validate 過。
- 測試補 x 來源的 fixture（離線）。

## 驗收條件

- [ ] `--diagnose` 顯示 x 可用（憑證生效）後真抓到 X 貼文，url 全部是永久連結
- [ ] 無憑證環境下 `arena collect` 正常跑完 reddit/hn 並明確警告 x skipped
- [ ] 新增 evidence 通過 `arena validate`，score 回填 votes 正常
- [ ] pytest 全綠；README 開發段補 X 憑證設定說明（憑證在 `~/.config/last30days/.env`，
      專案內不得出現任何 token）

## 安全紅線

- token/cookie **絕不**進 repo、不進 log、不進 commit、不貼進對話。
- 只認 `~/.config/last30days/.env`（引擎自有的使用者層設定檔）。
