# llm-arena · A1：專案骨架與 CLI

- 專案：`/home/jason/workspace/agent/llm-arena`
- 要讀：`docs/plan.md`（技術選型、任務 A1）、`docs/plan-overview.md`
- 階段：A（可立即動工，無前置）

## 目標

建立 Python 專案骨架，讓五個 CLI 子命令都能被叫到（尚未實作者回報「未實作」）。

## 要做的事

- `pyproject.toml`、`src/arena/`、`tests/`
- CLI 入口 `arena`，支援子命令：
  `fetch-models` / `collect` / `score` / `build` / `validate`
- 未實作的子命令要有明確訊息（不可靜默成功）
- 依 `docs/plan.md` 的技術選型：`httpx`、`pydantic`、`pytest`

## 驗收條件

- [ ] `arena --help` 列出五個子命令
- [ ] 每個子命令都能執行且不噴 traceback（未實作者回明確訊息）
- [ ] `pytest` 有一個 smoke test 會過
- [ ] `README.md` 的「開發」段落補上實際安裝與執行指令

## 備註

只建骨架，**不要**順手實作 fetch/collect/score 的內容（各自有獨立任務卡）。
