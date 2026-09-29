"""`arena score` 的實作佔位模組（任務 C3）。

C3 完成後由本模組提供 `run(args) -> int`；其他任務**不要**改本檔。
"""

from __future__ import annotations

import argparse
import sys

# 尚未實作時使用的結束碼；與 argparse 的使用錯誤（2）刻意區分開。
EXIT_NOT_IMPLEMENTED = 3


def run(args: argparse.Namespace) -> int:
    """JEV 逐則評分（任務 C3）。"""
    print(
        "arena score：尚未實作（見 docs/plan.md 任務 C3）\n"
        "  將以 JEV 家族模型對每則 evidence 分類並輸出校準機率。",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED
