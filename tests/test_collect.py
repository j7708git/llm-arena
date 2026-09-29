"""`arena collect` 的測試（任務 C2），全程離線。

引擎輸出以手刻 fixture 模擬（契約見 `docs/research/last30days-skill.md`），
runner 與 enricher 皆以假物件注入；HTTP 補缺用 `httpx.MockTransport`。
測試不連網、不寫 repo（輸出目錄在 pytest 的 tmp_path）。
"""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from arena import collect
from arena.cli import build_parser
from arena.enrich import HttpEnricher
from arena.schema import EvidenceRecord
from arena.validate import validate_path

FIXED_NOW = lambda: datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)  # noqa: E731
TODAY = "2026-09-29"

# 兩筆同文不同 url 的「爆紅轉貼」；一筆 jobs、一筆多模型、一筆中文、一筆缺 url。
BASE_RESULTS: list[dict] = [
    {
        "source": "reddit",
        "url": "https://www.reddit.com/r/x/comments/aaa/gpt5_first/",
        "published_at": "2026-09-22",
        "title": "GPT-5 is a joy to use",
        "summary": "I love GPT-5. submitted by /u/alice",
    },
    {
        "source": "reddit",
        "url": "https://www.reddit.com/r/y/comments/bbb/gpt5_reshare/",
        "published_at": "2026-09-23",
        "title": "GPT-5 is a joy to use",
        "summary": "I love GPT-5. submitted by /u/alice",
    },
    {
        "source": "hackernews",
        "url": "https://example.com/gpt5-review",
        "published_at": "2026-09-21",
        "title": "GPT-5 review",
        "summary": "A detailed look at GPT-5.",
    },
    {
        "source": "jobs",
        "url": "https://jobs.example.com/gpt5",
        "published_at": "2026-09-21",
        "title": "GPT-5 engineer wanted",
        "summary": "Hiring now.",
    },
    {
        "source": "hackernews",
        "url": "https://example.com/vs",
        "published_at": "2026-09-20",
        "title": "GPT-5 vs Claude Sonnet 4",
        "summary": "Which one wins?",
    },
    {
        "source": "reddit",
        "url": "https://www.reddit.com/r/z/comments/ccc/zh/",
        "published_at": "2026-09-20",
        "title": "這個模型很棒",
        "summary": "我很喜歡 GPT-5 的表現，真的很不錯。",
    },
    {
        "source": "reddit",
        "published_at": "2026-09-20",
        "title": "GPT-5 without url",
        "summary": "no url here",
    },
]


def make_payload(results: list[dict], status: dict | None = None) -> dict:
    return {
        "schema_version": "1.3",
        "query": "GPT-5",
        "generated_at": "2026-09-29T00:00:00Z",
        "window_days": 30,
        "source_status": status or {"reddit": "ok", "hackernews": "ok", "jobs": "ok"},
        "clusters": [],
        "results": results,
    }


class FakeRunner:
    """可注入的假引擎。`payloads` 可為 dict（依 query）或回傳 payload 的函式。"""

    def __init__(self, payloads) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, int, bool]] = []

    def run(self, query: str, *, days: int, deep: bool) -> dict:
        self.calls.append((query, days, deep))
        payload = self.payloads(query) if callable(self.payloads) else self.payloads[query]
        return copy.deepcopy(payload)


class SequenceRunner:
    """依序回傳一串 payload；用完後重複最後一個。"""

    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.calls = 0

    def run(self, query: str, *, days: int, deep: bool) -> dict:
        payload = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        return copy.deepcopy(payload)


class FakeEnricher:
    def __init__(self, authors: dict[str, str] | None = None, urls: dict[str, str] | None = None):
        self.authors = authors or {}
        self.urls = urls or {}

    def enrich(self, *, source: str, url: str, title: str, text: str):
        return self.authors.get(url), self.urls.get(url)


def make_args(tmp_path: Path, **overrides) -> argparse.Namespace:
    values = {
        "days": 30,
        "models": ["GPT-5"],
        "output_dir": str(tmp_path / "evidence"),
        "models_config": None,
        "deep": False,
        "retries": 0,
        "retry_backoff": 0.0,
        "sleep": 0.0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def run_collect(tmp_path: Path, runner, enricher=None, **overrides) -> int:
    args = make_args(tmp_path, **overrides)
    return collect.run(
        args,
        runner=runner,
        enricher=enricher or FakeEnricher(),
        sleep=lambda _seconds: None,
        now=FIXED_NOW,
    )


def read_today(tmp_path: Path) -> list[dict]:
    path = tmp_path / "evidence" / f"{TODAY}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# --- 去重 -------------------------------------------------------------------


def test_same_batch_duplicate_kept_once(tmp_path: Path) -> None:
    """同一則轉貼兩次（同文不同 url）只產出一筆。"""
    runner = FakeRunner({"GPT-5": make_payload(BASE_RESULTS)})

    assert run_collect(tmp_path, runner) == 0
    records = read_today(tmp_path)

    reddit_records = [record for record in records if record["source"] == "reddit"]
    assert len(reddit_records) == 1
    assert reddit_records[0]["url"].endswith("/aaa/gpt5_first/")


def test_cross_file_duplicate_is_skipped(tmp_path: Path) -> None:
    """既有其他日期的 evidence 檔已有同 hash 時不再寫入。"""
    out_dir = tmp_path / "evidence"
    out_dir.mkdir(parents=True)
    existing = {
        "hash": collect.content_hash("GPT-5 is a joy to use\nI love GPT-5. submitted by /u/alice"),
        "modelId": "openai/gpt-5",
        "source": "reddit",
        "url": "https://www.reddit.com/r/old/comments/old/old/",
        "author": None,
        "postedAt": "2026-09-01T00:00:00Z",
        "text": "GPT-5 is a joy to use\nI love GPT-5. submitted by /u/alice",
        "label": None,
        "prob": None,
        "judge": None,
    }
    (out_dir / "2026-09-01.jsonl").write_text(
        json.dumps(existing, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    assert run_collect(tmp_path, FakeRunner({"GPT-5": make_payload(BASE_RESULTS)})) == 0

    assert len((out_dir / "2026-09-01.jsonl").read_text().splitlines()) == 1
    records = read_today(tmp_path)
    # 跨檔重複（reddit）被跳過，只剩 HN 那筆。
    assert [record["source"] for record in records] == ["hn"]


def test_same_day_rerun_is_idempotent(tmp_path: Path) -> None:
    runner = FakeRunner({"GPT-5": make_payload(BASE_RESULTS)})

    assert run_collect(tmp_path, runner) == 0
    first = (tmp_path / "evidence" / f"{TODAY}.jsonl").read_text(encoding="utf-8")
    assert run_collect(tmp_path, runner) == 0
    second = (tmp_path / "evidence" / f"{TODAY}.jsonl").read_text(encoding="utf-8")

    assert first == second


# --- 過濾 -------------------------------------------------------------------


def test_source_whitelist_drops_jobs(tmp_path: Path) -> None:
    run_collect(tmp_path, FakeRunner({"GPT-5": make_payload(BASE_RESULTS)}))

    sources = {record["source"] for record in read_today(tmp_path)}
    assert sources <= {"reddit", "hn"}


def test_url_is_required(tmp_path: Path) -> None:
    """缺 url 的結果整筆丟棄（本 fixture 有效結果為 2 筆：reddit 首筆、HN 原文）。"""
    run_collect(tmp_path, FakeRunner({"GPT-5": make_payload(BASE_RESULTS)}))

    records = read_today(tmp_path)
    assert records
    assert all(record["url"] for record in records)
    assert all("without url" not in record["text"] for record in records)


def test_non_english_excluded(tmp_path: Path) -> None:
    run_collect(tmp_path, FakeRunner({"GPT-5": make_payload(BASE_RESULTS)}))

    assert all("這個模型很棒" not in record["text"] for record in read_today(tmp_path))


def test_multi_model_post_excluded(tmp_path: Path) -> None:
    run_collect(tmp_path, FakeRunner({"GPT-5": make_payload(BASE_RESULTS)}))

    assert all("vs Claude Sonnet 4" not in record["text"] for record in read_today(tmp_path))


def test_all_records_validate(tmp_path: Path) -> None:
    out_dir = tmp_path / "evidence"
    run_collect(tmp_path, FakeRunner({"GPT-5": make_payload(BASE_RESULTS)}))

    assert validate_path(out_dir / f"{TODAY}.jsonl") == []


# --- author 補缺 ------------------------------------------------------------


def test_author_backfilled_from_enricher(tmp_path: Path) -> None:
    url = "https://www.reddit.com/r/x/comments/aaa/gpt5_first/"
    enricher = FakeEnricher(authors={url: "u/alice"})

    run_collect(tmp_path, FakeRunner({"GPT-5": make_payload(BASE_RESULTS)}), enricher)

    record = read_today(tmp_path)[0]
    assert record["author"] == "u/alice"


def test_author_null_when_enrichment_fails_and_still_validates(tmp_path: Path) -> None:
    """補齊失敗→author 為 null，且該筆仍通過 schema（實作裁定第 6 條）。"""
    out_dir = tmp_path / "evidence"
    run_collect(tmp_path, FakeRunner({"GPT-5": make_payload(BASE_RESULTS)}), FakeEnricher())

    records = read_today(tmp_path)
    assert records
    assert all(record["author"] is None for record in records)
    assert validate_path(out_dir / f"{TODAY}.jsonl") == []
    for record in records:
        EvidenceRecord.model_validate(record)


def test_hn_enrichment_replaces_url_with_discussion_page(tmp_path: Path) -> None:
    hn_url = "https://example.com/gpt5-review"
    enricher = FakeEnricher(
        authors={hn_url: "pg"},
        urls={hn_url: "https://news.ycombinator.com/item?id=123456"},
    )

    run_collect(tmp_path, FakeRunner({"GPT-5": make_payload(BASE_RESULTS)}), enricher)

    hn_records = [record for record in read_today(tmp_path) if record["source"] == "hn"]
    assert hn_records
    assert hn_records[0]["url"] == "https://news.ycombinator.com/item?id=123456"
    assert hn_records[0]["author"] == "pg"


# --- 引擎健康狀態與重試 ------------------------------------------------------


def test_rate_limited_source_is_retried(tmp_path: Path) -> None:
    rate_limited = make_payload(
        BASE_RESULTS, status={"reddit": "rate-limited", "hackernews": "ok"}
    )
    healthy = make_payload(BASE_RESULTS, status={"reddit": "ok", "hackernews": "ok"})
    runner = SequenceRunner([rate_limited, healthy])
    delays: list[float] = []

    args = make_args(tmp_path, retries=2, retry_backoff=30.0)
    rc = collect.run(
        args,
        runner=runner,
        enricher=FakeEnricher(),
        sleep=delays.append,
        now=FIXED_NOW,
    )

    assert rc == 0
    assert runner.calls == 2
    assert delays == [30.0]  # 第一次退避 30s
    assert read_today(tmp_path)  # 重試成功後仍有資料


def test_unreachable_source_warns_but_does_not_abort(tmp_path: Path) -> None:
    status = {"reddit": "ok", "hackernews": "unreachable"}
    runner = FakeRunner({"GPT-5": make_payload(BASE_RESULTS, status=status)})
    args = make_args(tmp_path, retries=1, retry_backoff=5.0)

    rc = collect.run(
        args, runner=runner, enricher=FakeEnricher(), sleep=lambda _s: None, now=FIXED_NOW
    )

    assert rc == 0
    # reddit 仍成功，資料有落地；HN 失敗只警告。
    assert any(record["source"] == "reddit" for record in read_today(tmp_path))


def test_all_queries_failing_returns_error(tmp_path: Path) -> None:
    class BoomRunner:
        def run(self, query: str, *, days: int, deep: bool) -> dict:
            raise collect.CollectError("引擎掛掉")

    rc = run_collect(tmp_path, BoomRunner(), retries=1)

    assert rc == collect.EXIT_ERROR


# --- 原子寫入 ---------------------------------------------------------------


def test_atomic_write_leaves_no_partial_file_on_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "evidence"
    out_dir.mkdir(parents=True)
    path = out_dir / f"{TODAY}.jsonl"
    original = json.dumps(
        {
            "hash": "keepme",
            "modelId": "openai/gpt-5",
            "source": "reddit",
            "url": "https://www.reddit.com/r/x/comments/old/old/",
            "author": None,
            "postedAt": "2026-09-01T00:00:00Z",
            "text": "old",
            "label": None,
            "prob": None,
            "judge": None,
        },
        ensure_ascii=False,
    )
    path.write_text(original + "\n", encoding="utf-8")

    def boom(_fd: int) -> None:
        raise OSError("模擬寫入中崩潰")

    monkeypatch.setattr(collect.os, "fsync", boom)

    new_record = {
        "hash": "newone",
        "modelId": "openai/gpt-5",
        "source": "reddit",
        "url": "https://www.reddit.com/r/x/comments/new/new/",
        "author": None,
        "postedAt": "2026-09-22T00:00:00Z",
        "text": "new",
        "label": None,
        "prob": None,
        "judge": None,
    }
    with pytest.raises(OSError):
        collect.merge_and_write(path, [new_record])

    # 原檔內容不變、沒有殘留暫存檔。
    assert path.read_text(encoding="utf-8") == original + "\n"
    assert list(out_dir.glob(".*.tmp")) == []


# --- 補缺器（httpx.MockTransport） ------------------------------------------


def test_hn_enricher_uses_algolia() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "hn.algolia.com" in str(request.url)
        return httpx.Response(
            200,
            json={"hits": [{"objectID": "42", "author": "pg", "title": "GPT-5 review"}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    enricher = HttpEnricher(client=client)

    author, url = enricher.enrich(
        source="hn", url="https://example.com/original", title="GPT-5 review", text=""
    )

    assert author == "pg"
    assert url == "https://news.ycombinator.com/item?id=42"


def test_reddit_enricher_reads_author_from_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/comments/aaa/.json" in str(request.url)
        return httpx.Response(
            200,
            json=[
                {"kind": "Listing", "data": {"children": [{"kind": "t3", "data": {"author": "bob"}}]}},
                {"kind": "Listing", "data": {"children": []}},
            ],
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    enricher = HttpEnricher(client=client)

    author, url = enricher.enrich(
        source="reddit",
        url="https://www.reddit.com/r/x/comments/aaa/slug/",
        title="",
        text="no author in this text",
    )

    assert author == "u/bob"
    assert url is None


def test_reddit_enricher_json_failure_yields_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="blocked")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    enricher = HttpEnricher(client=client)

    author, url = enricher.enrich(
        source="reddit",
        url="https://www.reddit.com/r/x/comments/aaa/slug/",
        title="",
        text="no slash-u author",
    )

    assert author is None
    assert url is None


def test_reddit_enricher_prefers_author_from_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("有 /u/ 時不該打網路")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    enricher = HttpEnricher(client=client)

    author, _ = enricher.enrich(
        source="reddit",
        url="https://www.reddit.com/r/x/comments/aaa/slug/",
        title="",
        text="submitted by /u/carol to r/x",
    )

    assert author == "u/carol"


# --- 其他單元 ---------------------------------------------------------------


def test_query_uses_model_name_and_quick_by_default(tmp_path: Path) -> None:
    runner = FakeRunner({"GPT-5": make_payload(BASE_RESULTS)})
    run_collect(tmp_path, runner)

    assert runner.calls == [("GPT-5", 30, False)]


def test_deep_flag_is_forwarded(tmp_path: Path) -> None:
    runner = FakeRunner({"GPT-5": make_payload(BASE_RESULTS)})
    run_collect(tmp_path, runner, deep=True)

    assert runner.calls[0][2] is True


def test_posted_at_normalized_to_utc_iso(tmp_path: Path) -> None:
    run_collect(tmp_path, FakeRunner({"GPT-5": make_payload(BASE_RESULTS)}))

    for record in read_today(tmp_path):
        assert record["postedAt"].endswith("Z")


def test_cli_registers_collect_arguments() -> None:
    parser = build_parser()
    args = parser.parse_args(["collect", "--days", "7", "--models", "GPT-5"])

    assert args.days == 7
    assert args.models == ["GPT-5"]
    assert hasattr(args, "output_dir")


def test_unknown_model_selection_is_an_error(tmp_path: Path) -> None:
    args = make_args(tmp_path, models=["不存在模型"])

    rc = collect.run(args, runner=FakeRunner({}), enricher=FakeEnricher(), sleep=lambda _s: None)

    assert rc == collect.EXIT_ERROR


def test_offline_guard_blocks_default_runner(tmp_path: Path) -> None:
    """測試環境（PYTEST_CURRENT_TEST）未注入 runner 時不應連網，直接停手。"""
    args = make_args(tmp_path)

    rc = collect.run(args, enricher=FakeEnricher(), sleep=lambda _s: None)

    assert rc == collect.EXIT_ERROR
    assert not (tmp_path / "evidence").exists()
