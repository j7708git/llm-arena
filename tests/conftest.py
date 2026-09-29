"""pytest 全域防護（任務 C1 加入）。

兩條測試紀律，任何測試檔都適用：

1. **測試不可真的打網路**：``arena.fetch_models.fetch_models`` 預設被換成一律
   失敗（丟 :class:`~arena.openrouter.OpenRouterUnavailable`）；需要資料的測試
   自行 monkeypatch 覆寫。``arena.openrouter.fetch_models`` 不在此限，讓
   `httpx.MockTransport` 這類不連外的測試仍可直接驗證解析邏輯。
2. **測試不可改到 repo 的資料檔**：``fetch-models`` 的預設輸出路徑導到 pytest
   的暫存目錄，免得任何呼叫 ``run(Namespace())`` 的測試（例如 test_cli 的
   dispatch smoke test）覆寫 ``data/models.json``。
"""

from __future__ import annotations

import pytest

from arena import fetch_models as fm
from arena.openrouter import OpenRouterUnavailable


@pytest.fixture(autouse=True)
def _no_network_no_repo_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def _offline(*_args: object, **_kwargs: object) -> dict:
        raise OpenRouterUnavailable("測試環境不連外")

    monkeypatch.setattr(fm, "fetch_models", _offline)
    monkeypatch.setattr(fm, "DEFAULT_OUTPUT", tmp_path / "models.json")
