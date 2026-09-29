"""CLI 結構的 smoke test。

只驗證五個子命令都接得上、parser 結構正確；各子命令的「實作與結束碼」行為
由各任務自己的測試檔負責（fetch→test_fetch_models、collect→test_collect、
score→test_score、build→test_build、validate→test_validate）。
本檔**刻意不硬編碼**哪些命令還未實作，免得實作進度变更時要改好幾個地方。
"""

from __future__ import annotations

import pytest

from arena import __version__
from arena.cli import main

SUBCOMMANDS = ["fetch-models", "collect", "score", "build", "validate"]


def test_help_lists_all_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for command in SUBCOMMANDS:
        assert command in out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_prints_help() -> None:
    assert main([]) == 0


@pytest.mark.parametrize("command", SUBCOMMANDS)
def test_subcommands_dispatch_without_traceback(command: str) -> None:
    """每個子命令可被叫到並回傳 int（不噴 traceback；實作與否皆然）。"""
    result = main([command])
    assert isinstance(result, int)
