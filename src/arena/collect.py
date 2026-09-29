"""`arena collect` 的實作佔位模組（任務 C2）。

C2 完成後由本模組提供 `run(args) -> int`；其他任務**不要**改本檔。
"""

from __future__ import annotations

import argparse
import sys

# 尚未實作時使用的結束碼；與 argparse 的使用錯誤（2）刻意區分開。
EXIT_NOT_IMPLEMENTED = 3


def run(args: argparse.Namespace) -> int:
    """抓取近 30 天社群貼文（任務 C2）。"""
    print(
        "arena collect：尚未實作（見 docs/plan.md 任務 C2）\n"
        "  將把社群貼文落地為 data/evidence/YYYY-MM-DD.jsonl，並以內容 hash 去重。",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED
