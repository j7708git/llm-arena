"""`arena fetch-models` 的實作佔位模組（任務 C1）。

C1 完成後由本模組提供 `run(args) -> int`；其他任務**不要**改本檔。
"""

from __future__ import annotations

import argparse
import sys

# 尚未實作時使用的結束碼；與 argparse 的使用錯誤（2）刻意區分開。
EXIT_NOT_IMPLEMENTED = 3


def run(args: argparse.Namespace) -> int:
    """更新模型清單與定價（任務 C1）。"""
    print(
        "arena fetch-models：尚未實作（見 docs/plan.md 任務 C1）\n"
        "  將合併 config/models.yaml 人工清單與 OpenRouter /api/v1/models 的定價／context。",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED
