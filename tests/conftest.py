"""pytest 全域防護（C1 加入；C2 回報後由 PM 補強 score/collect）。

三條測試紀律，任何測試檔都適用：

1. **測試不可真的打網路**：``arena.fetch_models.fetch_models`` 預設被換成一律
   失敗（丟 :class:`~arena.openrouter.OpenRouterUnavailable`）；需要資料的測試
   自行 monkeypatch 覆寫。``arena.openrouter.fetch_models`` 不在此限，讓
   `httpx.MockTransport` 這類不連外的測試仍可直接驗證解析邏輯。
2. **測試不可改到 repo 的資料檔**：各管線命令的預設路徑一律導到 pytest 的
   暫存目錄／不存在的 glob，免得任何呼叫 ``run(Namespace())`` 的測試
   （例如 test_cli 的 dispatch smoke test）覆寫 ``data/models.json``、
   ``data/scores.json`` 或 ``data/evidence/*.jsonl``。
3. **collect 另自帶離線守門**（``ARENA_OFFLINE=1``／PYTEST_CURRENT_TEST），
   此處再設定一次環境變數作為雙重保險。
"""

from __future__ import annotations

import pytest

from arena import build as build_mod
from arena import collect as collect_mod
from arena import fetch_models as fm
from arena import score as score_mod
from arena.openrouter import OpenRouterUnavailable


@pytest.fixture(autouse=True)
def _no_network_no_repo_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def _offline(*_args: object, **_kwargs: object) -> dict:
        raise OpenRouterUnavailable("測試環境不連外")

    # fetch-models：不連外、輸出導到暫存目錄。
    monkeypatch.setattr(fm, "fetch_models", _offline)
    monkeypatch.setattr(fm, "DEFAULT_OUTPUT", tmp_path / "models.json")

    # score：預設 glob 改成永遠命不中，避免載入 laya 並覆寫 repo evidence 檔。
    monkeypatch.setattr(
        score_mod, "DEFAULT_EVIDENCE_GLOB", "_pytest_offline_nothing_*.jsonl"
    )

    # build（C4）：輸入與輸出都導到暫存目錄／命不中的 glob，避免 dispatch
    # smoke test（`main(["build"])`）讀寫 repo 的 data/evidence 與 data/scores.json。
    monkeypatch.setattr(build_mod, "DEFAULT_OUTPUT", tmp_path / "scores.json")
    monkeypatch.setattr(
        build_mod, "DEFAULT_EVIDENCE_GLOB", "_pytest_offline_nothing_*.jsonl"
    )
    monkeypatch.setattr(build_mod, "DEFAULT_MODELS", tmp_path / "models.json")

    # collect：輸出目錄與去重掃描範圍導到暫存目錄，並強制離線。
    monkeypatch.setattr(
        collect_mod, "DEFAULT_OUTPUT_DIR", tmp_path / "evidence-offline"
    )
    monkeypatch.setenv("ARENA_OFFLINE", "1")
