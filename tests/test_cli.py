"""CLI 骨架的 smoke test。

只驗證五個子命令都接得上、未實作者明確回報，不驗證各子命令的商業邏輯
（那屬於 C1～C4 的任務範圍；validate 的驗證邏輯見 test_validate.py）。
"""

from __future__ import annotations

import pytest

from arena import __version__
from arena.cli import EXIT_NOT_IMPLEMENTED, main

# 五個子命令都要出現在 --help；A2 完成後 validate 已實作，不再算未實作。
SUBCOMMANDS = ["fetch-models", "collect", "score", "build", "validate"]
UNIMPLEMENTED_COMMANDS = ["fetch-models", "collect", "score", "build"]


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


@pytest.mark.parametrize("command", UNIMPLEMENTED_COMMANDS)
def test_unimplemented_commands_report_clearly(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main([command])

    captured = capsys.readouterr()
    assert exit_code == EXIT_NOT_IMPLEMENTED
    assert "尚未實作" in captured.err
    assert command in captured.err
    assert captured.out == ""
