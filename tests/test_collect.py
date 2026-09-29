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
        "votes": None,
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
            "votes": None,
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
        "votes": None,
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


def test_query_uses_model_name_and_default_depth(tmp_path: Path) -> None:
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


# --- X／Twitter 來源 --------------------------------------------------------

# X 列在 agent JSON 的實際形狀（2026-09-29 真抓 engine 輸出）：title 是 summary
# 截斷前 140 字元，url 為 https://x.com/<handle>/status/<id>，無 author 欄位。
X_POST: dict = {
    "source": "x",
    "url": "https://x.com/alice/status/1840000000000000001",
    "published_at": "2026-09-24",
    "title": "GPT-5 is a joy to use\n\nI love it",
    "summary": "GPT-5 is a joy to use\n\nI love it a lot. Best model this year.",
}

X_MISSING_URL: dict = {
    "source": "x",
    "published_at": "2026-09-24",
    "title": "GPT-5 without url",
    "summary": "no permalink on this one",
}

X_NON_ENGLISH: dict = {
    "source": "x",
    "url": "https://x.com/bob/status/1840000000000000002",
    "published_at": "2026-09-23",
    "title": "這個模型很棒",
    "summary": "我很喜歡 GPT-5 的表現，真的很不錯。",
}


def test_x_post_is_collected_with_author_from_url(tmp_path: Path) -> None:
    """X 列正常轉換：source=x、url 永久連結、author 取自路徑、date 正規化。"""
    runner = FakeRunner({"GPT-5": make_payload([X_POST])})

    assert run_collect(tmp_path, runner) == 0

    records = read_today(tmp_path)
    assert len(records) == 1
    record = records[0]
    assert record["source"] == "x"
    assert record["url"] == "https://x.com/alice/status/1840000000000000001"
    assert record["author"] == "@alice"
    assert record["postedAt"] == "2026-09-24T00:00:00Z"
    # title 是 summary 的截斷前綴，text 只留 summary（不重複）。
    assert record["text"] == X_POST["summary"]
    assert record["votes"] is None and record["judge"] is None


def test_x_missing_url_dropped(tmp_path: Path) -> None:
    run_collect(tmp_path, FakeRunner({"GPT-5": make_payload([X_MISSING_URL])}))

    assert read_today(tmp_path) == []


def test_x_non_english_excluded(tmp_path: Path) -> None:
    run_collect(tmp_path, FakeRunner({"GPT-5": make_payload([X_NON_ENGLISH])}))

    assert read_today(tmp_path) == []


def test_x_repost_of_reddit_is_deduplicated(tmp_path: Path) -> None:
    """跨來源同文轉貼：Reddit 貼文與 X 轉推同文時只留先到的一筆。"""
    shared_text = "GPT-5 is a joy to use\nI love GPT-5. submitted by /u/alice"
    reddit = {
        "source": "reddit",
        "url": "https://www.reddit.com/r/x/comments/aaa/gpt5_first/",
        "published_at": "2026-09-22",
        "title": "GPT-5 is a joy to use",
        "summary": "I love GPT-5. submitted by /u/alice",
    }
    x_repost = {
        "source": "x",
        "url": "https://x.com/alice/status/1840000000000000003",
        "published_at": "2026-09-23",
        "title": "GPT-5 is a joy to use",
        "summary": "I love GPT-5. submitted by /u/alice",
    }
    runner = FakeRunner({"GPT-5": make_payload([reddit, x_repost])})

    assert run_collect(tmp_path, runner) == 0

    records = read_today(tmp_path)
    assert len(records) == 1
    assert records[0]["source"] == "reddit"
    assert records[0]["hash"] == collect.content_hash(shared_text)


def test_x_author_missing_when_url_is_not_permalink(tmp_path: Path) -> None:
    """url 非標準永久連結時，author 為 null，但該筆仍可落地（schema 允許）。"""
    odd = {
        "source": "x",
        "url": "https://x.com/i/web/status/1840000000000000004",
        "published_at": "2026-09-24",
        "title": "GPT-5 thoughts",
        "summary": "GPT-5 thoughts and more.",
    }
    run_collect(tmp_path, FakeRunner({"GPT-5": make_payload([odd])}))

    records = read_today(tmp_path)
    assert len(records) == 1
    assert records[0]["author"] is None


def test_x_skipped_unconfigured_warns_and_continues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """無憑證（skipped-unconfigured）：跳過 x、明確警告、其他來源照常、退出碼 0。"""
    status = {"reddit": "ok", "hackernews": "ok", "x": "skipped-unconfigured"}
    runner = FakeRunner({"GPT-5": make_payload(BASE_RESULTS, status=status)})
    args = make_args(tmp_path, retries=2, retry_backoff=5.0)

    rc = collect.run(
        args,
        runner=runner,
        enricher=FakeEnricher(),
        sleep=lambda _s: None,
        now=FIXED_NOW,
    )

    assert rc == 0
    # 預期跳過不重試：即使 retries>0 也只查一次。
    assert len(runner.calls) == 1
    assert any(record["source"] == "reddit" for record in read_today(tmp_path))
    err = capsys.readouterr().err
    assert "x" in err and "skipped-unconfigured" in err


def test_unconfigured_sources_classification() -> None:
    status = {"reddit": "ok", "x": "skipped-unconfigured"}

    assert collect.unconfigured_sources(status) == ["x"]
    assert collect.unhealthy_sources(status) == []


def test_x_author_parsing_variants() -> None:
    assert collect.x_author_from_url("https://x.com/a_b/status/123") == "@a_b"
    assert collect.x_author_from_url("https://twitter.com/a_b/status/123") == "@a_b"
    assert collect.x_author_from_url("https://www.x.com/a_b/status/123") == "@a_b"
    # 內部轉址路徑沒有 <handle>/status/<id> 形狀，不誤判成作者。
    assert collect.x_author_from_url("https://x.com/i/web/status/123") is None
    assert collect.x_author_from_url("https://example.com/a/status/123") is None
    assert collect.x_author_from_url("") is None


def test_compose_text_drops_truncated_x_title() -> None:
    """X 的 title 是 summary 的前綴（可能斷在詞中間），不應重複併入 text。"""
    summary = "GPT-5 is a joy to use and the best model I have tried this year."
    title = summary[:20]  # 斷在「...and the be」中間，下一個字元不是空白

    assert collect.compose_text(title, summary) == summary


def _capture_engine_command(monkeypatch: pytest.MonkeyPatch, *, deep: bool) -> list[str]:
    captured: dict[str, list[str]] = {}

    class FakeProc:
        returncode = 0
        stdout = json.dumps(make_payload([]))
        stderr = ""

    def fake_run(command, **_kwargs):
        captured["command"] = list(command)
        return FakeProc()

    monkeypatch.setattr(collect.subprocess, "run", fake_run)
    runner = collect.SubprocessRunner(
        python=Path("/usr/bin/python3.12"), script=Path("vendor/last30days/last30days.py")
    )
    runner.run("GPT-5", days=30, deep=deep)
    return captured["command"]


def test_subprocess_runner_requests_x_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """引擎命令必須明確要求 x，且不可用 --quick（quick 會把 x 擠掉）。"""
    command = _capture_engine_command(monkeypatch, deep=False)

    assert command[command.index("--search") + 1] == "reddit,hackernews,x"
    assert "--quick" not in command
    assert "--deep" not in command


def test_subprocess_runner_deep_flag_is_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    command = _capture_engine_command(monkeypatch, deep=True)

    assert "--deep" in command
    assert command[command.index("--search") + 1] == "reddit,hackernews,x"


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


# --- 歸屬三態（C6，修正引擎模糊比對造成的模型錯歸屬） ------------------------

SONNET4: dict = {"id": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4"}
# 完整清單（含 C2b 誤歸情境的 Sonnet 5.5 與 GPT-6 Sol）。
CATALOGUE: list[dict] = [
    SONNET4,
    {"id": "anthropic/claude-sonnet-5.5", "name": "Claude Sonnet 5.5"},
    {"id": "openai/gpt-5", "name": "GPT-5"},
    {"id": "openai/gpt-6-sol", "name": "GPT-6 Sol"},
]


def engine_result(text: str, slug: str = "post") -> dict:
    return {
        "source": "reddit",
        "url": f"https://www.reddit.com/r/x/comments/{slug}/p/",
        "published_at": "2026-09-22",
        "title": text,
        "summary": "",
    }


def build_as_sonnet4(text: str, slug: str = "post"):
    """以 query=Claude Sonnet 4 對單則文字跑 build_records，回傳 (records, stats)。"""
    stats = collect.BuildStats()
    records = collect.build_records(
        {"results": [engine_result(text, slug)]}, SONNET4, CATALOGUE, stats
    )
    return records, stats


def test_model_aliases_include_short_form_and_drop_bare_versions() -> None:
    assert collect.model_aliases(SONNET4) == (
        "Claude Sonnet 4",
        "claude-sonnet-4",
        "Sonnet 4",
    )
    # 去首詞的純版本號（4.7）不含字母，不成為別名。
    assert collect.model_aliases({"id": "x-ai/grok-4.7", "name": "Grok 4.7"}) == (
        "Grok 4.7",
        "grok-4.7",
    )
    # 去首詞後綴不含版本號數字者不採用（'Sol' 太通用）。
    assert collect.model_aliases({"id": "openai/gpt-6-sol", "name": "GPT-6 Sol"}) == (
        "GPT-6 Sol",
        "gpt-6-sol",
    )


def test_misattributed_other_model_dropped() -> None:
    """查 Sonnet 4、貼文只提 Sonnet 5.5 → 丟並計入 misattributed（C6 必測）。"""
    records, stats = build_as_sonnet4("Sonnet 5.5 is a generational leap")

    assert records == []
    assert stats.misattributed == 1
    assert stats.dropped_multi_model == 0


def test_misattributed_other_model_full_name_dropped() -> None:
    records, stats = build_as_sonnet4("GPT-5 is still my daily driver")

    assert records == []
    assert stats.misattributed == 1


def test_unattributed_post_kept() -> None:
    """兩者皆未出現（只寫 this model）→ 留，靠引擎 relevance。"""
    records, stats = build_as_sonnet4("This model is great and I use it daily")

    assert len(records) == 1
    assert records[0]["modelId"] == SONNET4["id"]
    assert stats.misattributed == 0


def test_query_short_name_kept() -> None:
    records, stats = build_as_sonnet4("Sonnet 4 is great")

    assert len(records) == 1
    assert records[0]["modelId"] == SONNET4["id"]
    assert stats.misattributed == 0


def test_query_full_name_kept() -> None:
    records, _ = build_as_sonnet4("Claude Sonnet 4 is great")

    assert len(records) == 1


def test_other_version_number_is_not_query_match() -> None:
    """詞邊界：Sonnet 4.5 不算提及 Sonnet 4，也不被誤判成其他清單模型 → 留。"""
    records, stats = build_as_sonnet4("Sonnet 4.5 feels nicer")

    assert len(records) == 1
    assert stats.misattributed == 0


def test_multi_model_rule_takes_precedence() -> None:
    """同時提及 query 與其他模型（≥2 個全名）→ 走既有 multi-model 丟除。"""
    records, stats = build_as_sonnet4("Claude Sonnet 4 vs GPT-5")

    assert records == []
    assert stats.dropped_multi_model == 1
    assert stats.misattributed == 0


def test_collect_summary_reports_misattributed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """端到端：誤歸屬的貼文不落地，且摘要印出誤歸屬計數。"""
    payload = make_payload([engine_result("Sonnet 5.5 is a generational leap", "m1")])
    runner = FakeRunner({"GPT-5": payload})

    assert run_collect(tmp_path, runner) == 0

    assert read_today(tmp_path) == []
    assert "誤歸屬 1" in capsys.readouterr().out

