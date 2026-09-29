"""`arena build` 的實作佔位模組（任務 C4）。

C4 完成後由本模組提供 `run(args) -> int`；其他任務**不要**改本檔。
"""

from __future__ import annotations

import argparse
import sys

# 尚未實作時使用的結束碼；與 argparse 的使用錯誤（2）刻意區分開。
EXIT_NOT_IMPLEMENTED = 3


def run(args: argparse.Namespace) -> int:
    """由 evidence 聚合出 data/scores.json（任務 C4）。"""
    print(
        "arena build：尚未實作（見 docs/plan.md 任務 C4）\n"
        "  將由 evidence 以公式聚合出 data/scores.json。",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED
