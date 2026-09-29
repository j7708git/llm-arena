# vendor/last30days

`arena collect`（任務 C2）實際使用的社群抓取引擎。**這是第三方程式碼，不是本專案的一部分**，
放在 `vendor/` 只為了可重現地 pin 版本；請勿在此目錄直接修改。

## 來源與版本

| 項目 | 值 |
| --- | --- |
| 上游 repo | <https://github.com/mvanhorn/last30days-skill> |
| 授權 | MIT（見同目錄 `LICENSE`） |
| 技能版本 | v3.25.0 |
| pin commit | `084662b501fb0dba95bd55eff0c258d35e0dc499`（2026-09-22） |
| 引擎入口 | `last30days.py` |
| 引擎相依 | `lib/`（與 `last30days.py` 同層；engine 以 `sys.path.insert` 匯入 `lib`） |
| Python 需求 | **>= 3.12**（上游 `pyproject.toml` 的 `requires-python`） |
| 外部套件 | 無（引擎只依賴 Python 標準函式庫） |

`lib/` 內含一個 X/Twitter 用的 vendored Node 小工具（`lib/vendor/bird-search`），
本專案只走 Reddit／HN，不會用到；一併保留是為了讓引擎目錄與上游一致、降低漏檔風險。

## 從哪裡來（可重現的 vendor 步驟）

```bash
git clone https://github.com/mvanhorn/last30days-skill.git /tmp/last30days-skill
cd /tmp/last30days-skill
git checkout 084662b501fb0dba95bd55eff0c258d35e0dc499

# 只取引擎與授權
cp skills/last30days/scripts/last30days.py <repo>/vendor/last30days/
cp -r skills/last30days/scripts/lib            <repo>/vendor/last30days/lib
cp LICENSE                                     <repo>/vendor/last30days/LICENSE
```

## 授權

上游為 MIT，`LICENSE` 已隨此目錄一起 vendor。使用與再散布請遵守該授權條款。

## Python 環境

引擎需要 Python >= 3.12。本專案以自己的 `.venv` 執行（`arena collect` 會自動優先找
`<repo>/.venv/bin/python`）：

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"
```

也可以改用系統上任一個 3.12+ 的 Python，透過環境變數覆寫：

```bash
ARENA_ENGINE_PYTHON=/path/to/python3.12 .venv/bin/arena collect
```

引擎的零設定可用來源為 Reddit + Hacker News（另有 Polymarket／GitHub／grounding，
但對「LLM 模型評比」題幾乎沒料）；Reddit keyless 路徑會被限流，執行時需要退避重試。
選型、契約與坑詳見 `docs/research/last30days-skill.md`。

## 升級方式

1. 取得新的上游 commit（或 release tag）。
2. 依上面「可重現的 vendor 步驟」重新複製 `last30days.py`、`lib/`、`LICENSE`。
3. 更新本檔的「pin commit」與版本欄位。
4. 跑 `pytest`（collect 的測試用 fixture 與引擎解耦，升級後仍應離線全綠）。
