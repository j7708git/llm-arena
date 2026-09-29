"""arena 命令列入口。

五個子命令都能被叫到；`validate` 已實作（任務 A2，驗證邏輯在
`arena.validate`／`arena.schema`），其餘尚未實作的子命令會印出明確訊息
並以非 0 結束碼收場（避免被誤認為成功）。各子命令的實作見 `docs/plan.md`
的任務拆分（C1 fetch-models、C2 collect、C3 score、C4 build、A2 validate）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Sequence

from arena import __version__
from arena.build import run as run_build
from arena.collect import run as run_collect
from arena.fetch_models import run as run_fetch_models
from arena.score import run as run_score
from arena.validate import EXIT_INVALID, EXIT_OK, validate_path

# `arena validate` 未指定路徑時檢查的預設檔案。
DEFAULT_VALIDATE_PATHS = ["data/scores.json"]


def cmd_fetch_models(args: argparse.Namespace) -> int:
    """更新模型清單與定價（任務 C1，實作在 arena.fetch_models）。"""
    return run_fetch_models(args)


def cmd_collect(args: argparse.Namespace) -> int:
    """抓取近 30 天社群貼文（任務 C2，實作在 arena.collect）。"""
    return run_collect(args)


def cmd_score(args: argparse.Namespace) -> int:
    """JEV 逐則評分（任務 C3，實作在 arena.score）。"""
    return run_score(args)


def cmd_build(args: argparse.Namespace) -> int:
    """由 evidence 聚合出 data/scores.json（任務 C4，實作在 arena.build）。"""
    return run_build(args)


def cmd_validate(args: argparse.Namespace) -> int:
    """檢查資料是否符合 schema v1（任務 A2）。

    合法回傳 0；任一檔案不合法回傳 1，並逐條列出「檔案：位置：問題」。
    """
    paths: list[str] = args.paths or DEFAULT_VALIDATE_PATHS

    errors: list[str] = []
    checked: list[str] = []
    for raw_path in paths:
        file_errors = validate_path(Path(raw_path))
        if file_errors:
            errors.extend(file_errors)
        else:
            checked.append(raw_path)

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        print(
            f"validate：{len(errors)} 個問題，資料不符合 schema v1。",
            file=sys.stderr,
        )
        return EXIT_INVALID

    for path in checked:
        print(f"OK {path}：符合 schema v1")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """建立 arena 的 argparse 解析器。"""
    parser = argparse.ArgumentParser(
        prog="arena",
        description="LLM 社群評價排行榜的資料管線。",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"arena {__version__}",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="{fetch-models,collect,score,build,validate}",
    )

    commands: list[tuple[str, str, Callable[[argparse.Namespace], int]]] = [
        ("fetch-models", "更新模型清單與定價（人工清單 + OpenRouter）", cmd_fetch_models),
        ("collect", "抓取近 30 天社群貼文，落地為 data/evidence/*.jsonl", cmd_collect),
        ("score", "以 JEV 對逐則貼文評分（含校準機率）", cmd_score),
        ("build", "由 evidence 聚合出 data/scores.json", cmd_build),
        ("validate", "檢查資料是否符合 schema v1", cmd_validate),
    ]

    for name, help_text, handler in commands:
        sub = subparsers.add_parser(name, help=help_text, description=help_text)
        if name == "validate":
            # 允許指定要檢查的檔案；未指定時之後會用預設的 data/scores.json。
            sub.add_argument(
                "paths",
                metavar="PATH",
                nargs="*",
                help="要檢查的檔案（預設 data/scores.json）",
            )
        sub.set_defaults(func=handler)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主進入點；回傳行程結束碼。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help()
        return 0

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
