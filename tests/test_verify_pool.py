"""``tools/verify_pool.py`` 的離線測試（C11，實作裁定 17）。

驗收重點：

- 繼承判定擴為「``thread.title`` **或** ``thread.body`` 精確提及該模型」。
- 帶 ``thread`` 的 X 推文列（含只帶 ``body``）會被判為違規。

這些測試只呼叫純函式，**不連網**（url 連線檢查不在測試範圍）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

from arena.collect import load_manual_models  # noqa: E402
from verify_pool import (  # noqa: E402
    INHERITED,
    SELF,
    attribution_source,
    thread_field_issues,
)

CATALOGUE = load_manual_models(ROOT / "config" / "models.yaml")
BY_ID = {model["id"]: model for model in CATALOGUE}
OPUS55 = BY_ID["anthropic/claude-opus-5.5"]

THREAD_URL = "https://www.reddit.com/r/ClaudeCode/comments/1wov62z/got_mogged_by_claude_opus/"


def _row(**overrides: object) -> dict:
    base = {
        "modelId": "anthropic/claude-opus-5.5",
        "source": "reddit",
        "url": "https://www.reddit.com/r/ClaudeCode/comments/1wov62z/x/abc/",
        "text": "no model name mentioned in this comment",
    }
    base.update(overrides)
    return base


def test_self_mention_still_passes() -> None:
    row = _row(text="Claude Opus 5.5 is great")
    source, reason = attribution_source(row, OPUS55, CATALOGUE)
    assert source == SELF, reason


def test_inherited_via_thread_title() -> None:
    row = _row(
        thread={
            "url": THREAD_URL,
            "title": "Claude Opus 5.5 impressions",
            "modelId": "anthropic/claude-opus-5.5",
        }
    )
    source, reason = attribution_source(row, OPUS55, CATALOGUE)
    assert source == INHERITED, reason


def test_inherited_via_thread_body_when_title_lacks_version() -> None:
    """標題不帶版本號、版本只在 body：擴充後的判定要能佐證（裁定 17）。"""
    row = _row(
        thread={
            "url": THREAD_URL,
            "title": "got mogged by claude opus",
            "modelId": "anthropic/claude-opus-5.5",
            "body": "wow opus 5.5 on medium is clearing astra's long-windedness",
        }
    )
    source, reason = attribution_source(row, OPUS55, CATALOGUE)
    assert source == INHERITED, reason


def test_thread_without_version_anywhere_still_fails() -> None:
    """title 與 body 都沒有版本號時如實不通過，不靜默放行。"""
    row = _row(
        thread={
            "url": THREAD_URL,
            "title": "got mogged by claude opus",
            "modelId": "anthropic/claude-opus-5.5",
            "body": "this thing is wild, no version number here",
        }
    )
    source, reason = attribution_source(row, OPUS55, CATALOGUE)
    assert source is None
    assert "thread.title" in reason


def test_thread_model_mismatch_fails() -> None:
    row = _row(
        thread={
            "url": THREAD_URL,
            "title": "Claude Opus 5.5 impressions",
            "modelId": "anthropic/claude-sonnet-5.5",
        }
    )
    source, _ = attribution_source(row, OPUS55, CATALOGUE)
    assert source is None


def test_healthy_thread_row_has_no_issues() -> None:
    row = _row(
        thread={
            "url": THREAD_URL,
            "title": "Claude Opus 5.5 impressions",
            "modelId": "anthropic/claude-opus-5.5",
            "body": "body text is fine",
        }
    )
    assert thread_field_issues([row]) == []


def test_x_row_with_thread_body_is_rejected() -> None:
    """X 推文列不得帶 thread（含 body）——即使只帶 body 也要被擋。"""
    row = _row(
        source="x",
        thread={
            "url": "https://x.com/a/status/1",
            "title": "Claude Opus 5.5",
            "modelId": "anthropic/claude-opus-5.5",
            "body": "body on an X row is not allowed",
        },
    )
    issues = thread_field_issues([row])
    assert any("X 推文" in message for message in issues)


def test_thread_missing_required_field_is_flagged() -> None:
    row = _row(
        thread={
            "url": THREAD_URL,
            "modelId": "anthropic/claude-opus-5.5",
        }
    )
    issues = thread_field_issues([row])
    assert any("title" in message for message in issues)
