# llm-arena · R3：last30days 技能抓取能力研究

- 專案：`/home/jason/workspace/agent/llm-arena`
- 要讀：`docs/plan.md`（C2）、`docs/plan-overview.md`
- 階段：研究（C2 的前置）

## 目標

確認 `last30days` 技能實際抓得到什麼，這決定排行榜的可信度上限。

## 要調查

- 支援哪些來源？（Reddit / X / Hacker News / 論壇 / 部落格…）
- 時間窗口是不是固定的 30 天、能不能調整
- 能不能**按關鍵字或模型名稱**查詢
- 回傳格式是什麼（貼文原文？連結？作者？時間？）
- 需不需要憑證或 API key、有無 rate limit
- 每則貼文能不能拿到**永久連結**（schema 的 `evidence[].url` 需要）

## 產出

`docs/research/last30days-skill.md`，包含：

1. 支援來源與覆蓋率說明
2. 一次實際抓取：挑 2～3 個模型名稱，記錄抓到幾筆、各來源分佈
3. 限制清單（哪些來源抓不到、會不會漏、時間窗口的偏誤）

## 驗收條件

- [ ] 有實際抓取的筆數與來源分佈，不是只寫「應該可以」
- [ ] 明確確認能否取得永久連結
- [ ] 寫出「近 30 天窗口會偏袒新模型」這類偏誤在呈現上要怎麼標示

## 下游

`llm-arena-c2-collect.md`
