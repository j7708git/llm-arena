"""`arena collect` 的測試（任務 C2；C9 改為留言逐則＋版本精確歸屬），全程離線。

引擎輸出以手刻 fixture 模擬（契約見 `docs/research/last30days-skill.md`），
runner、enricher 與 comment fetcher 皆以假物件注入；HTTP 補缺用 `httpx.MockTransport`。
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
from arena.enrich import HttpCommentFetcher, HttpEnricher, ThreadComment
from arena.schema import EvidenceRecord
from arena.validate import validate_path

FIXED_NOW = lambda: datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)  # noqa: E731
TODAY = "2026-09-29"

# C9：清單 v2 裡的模型名（config/models.yaml 換血後仍存在）。
SONNET55 = "Claude Sonnet 5.5"
SONNET5_NAME = "Claude Sonnet 5"
GPT6_SOL = "GPT-6 Sol"

# 兩筆同文不同 url 的「爆紅轉貼」（以留言形式呈現）；一筆 jobs、一筆多模型、
# 一筆中文、一筆缺 url。
BASE_RESULTS: list[dict] = [
    {
        "source": "reddit",
        "url": "https://www.reddit.com/r/x/comments/aaa/gpt5_first/",
        "published_at": "2026-09-22",
        "title": "Sonnet 5.5 is a joy to use",
        "summary": "I love Sonnet 5.5. submitted by /u/alice",
    },
    {
        "source": "reddit",
        "url": "https://www.reddit.com/r/y/comments/bbb/gpt5_reshare/",
        "published_at": "2026-09-23",
        "title": "Sonnet 5.5 is a joy to use",
        "summary": "I love Sonnet 5.5. submitted by /u/alice",
    },
    {
        "source": "hackernews",
        "url": "https://example.com/sonnet55-review",
        "published_at": "2026-09-21",
        "title": "Sonnet 5.5 review",
        "summary": "A detailed look at Sonnet 5.5.",
    },
    {
        "source": "jobs",
        "url": "https://jobs.example.com/sonnet55",
        "published_at": "2026-09-21",
        "title": "Sonnet 5.5 engineer wanted",
        "summary": "Hiring now.",
    },
    {
        "source": "hackernews",
        "url": "https://example.com/vs",
        "published_at": "2026-09-20",
        "title": "Sonnet 5.5 vs GPT-6 Sol",
        "summary": "Which one wins?",
    },
    {
        "source": "reddit",
        "url": "https://www.reddit.com/r/z/comments/ccc/zh/",
        "published_at": "2026-09-20",
        "title": "這個模型很棒",
        "summary": "我很喜歡 Sonnet 5.5 的表現，真的很不錯。",
    },
    {
        "source": "reddit",
        "published_at": "2026-09-20",
        "title": "Sonnet 5.5 without url",
        "summary": "no url here",
    },
]

REDDIT_FIRST = "https://www.reddit.com/r/x/comments/aaa/gpt5_first/"
REDDIT_SECOND = "https://www.reddit.com/r/y/comments/bbb/gpt5_reshare/"
HN_THREAD = "https://example.com/sonnet55-review"

def comment(
    text: str,
    *,
    source: str,
    url: str,
    author: str | None = "u/someone",
    posted_at: str = "2026-09-23T00:00:00Z",
) -> ThreadComment:
    """組一則假留言（欄位對應 :class:`arena.enrich.ThreadComment`）。"""
    return ThreadComment(url=url, author=author, posted_at=posted_at, text=text)


# BASE_RESULTS 每個討論串的假留言（C9：reddit／hn 的 row 都是留言級）。
BASE_COMMENTS: dict[tuple[str, str], list[ThreadComment]] = {
    ("reddit", REDDIT_FIRST): [
        comment(
            "Sonnet 5.5 is a joy to use\nI love Sonnet 5.5. submitted by /u/alice",
            source="reddit",
            url=f"{REDDIT_FIRST}comment/c1/",
            author="u/alice",
        )
    ],
    # 同文轉貼：hash 相同，去重後只留先到的一筆。
    ("reddit", REDDIT_SECOND): [
        comment(
            "Sonnet 5.5 is a joy to use\nI love Sonnet 5.5. submitted by /u/alice",
            source="reddit",
            url=f"{REDDIT_SECOND}comment/c2/",
            author="u/alice",
        )
    ],
    ("hn", HN_THREAD): [
        comment(
            "A detailed look at Sonnet 5.5.",
            source="hn",
            url="https://news.ycombinator.com/item?id=123456",
            author="pg",
            posted_at="2026-09-21T00:00:00Z",
        )
    ],
    # 多模型串與中文串：假留言也帶對應內容，方便驗證歸屬過濾。
    ("hn", "https://example.com/vs"): [
        comment(
            "Sonnet 5.5 vs GPT-6 Sol: which one wins?",
            source="hn",
            url="https://news.ycombinator.com/item?id=999",
        )
    ],
    ("reddit", "https://www.reddit.com/r/z/comments/ccc/zh/"): [
        comment("這個模型很棒，我很喜歡 Sonnet 5.5", source="reddit", url="zh/comment/c3/")
    ],
}


def make_payload(results: list[dict], status: dict | None = None) -> dict:
    return {
        "schema_version": "1.3",
        "query": SONNET55,
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


class FakeCommentFetcher:
    """假留言抓取器：依 (source, thread url) 回傳預先備好的 :class:`ThreadComment`。"""

    def __init__(self, comments: dict[tuple[str, str], list] | None = None) -> None:
        self.comments = dict(BASE_COMMENTS if comments is None else comments)
        self.calls: list[tuple[str, str]] = []

    def thread_comments(self, *, source: str, url: str, title: str):
        self.calls.append((source, url))
        return self.comments.get((source, url), [])


def make_args(tmp_path: Path, **overrides) -> argparse.Namespace:
    values = {
        "days": 30,
        "models": [SONNET55],
        "output_dir": str(tmp_path / "evidence"),
        "models_config": None,
        "deep": False,
        "retries": 0,
        "retry_backoff": 0.0,
        "sleep": 0.0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def run_collect(
    tmp_path: Path,
    runner,
    enricher=None,
    comment_fetcher=None,
    **overrides,
) -> int:
    args = make_args(tmp_path, **overrides)
    return collect.run(
        args,
        runner=runner,
        enricher=enricher or FakeEnricher(),
        comment_fetcher=comment_fetcher or FakeCommentFetcher(),
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
    runner = FakeRunner({SONNET55: make_payload(BASE_RESULTS)})

    assert run_collect(tmp_path, runner) == 0
    records = read_today(tmp_path)

    reddit_records = [record for record in records if record["source"] == "reddit"]
    assert len(reddit_records) == 1
    assert reddit_records[0]["url"] == f"{REDDIT_FIRST}comment/c1/"


def test_cross_file_duplicate_is_skipped(tmp_path: Path) -> None:
    """既有其他日期的 evidence 檔已有同 hash 時不再寫入。"""
    out_dir = tmp_path / "evidence"
    out_dir.mkdir(parents=True)
    text = "Sonnet 5.5 is a joy to use\nI love Sonnet 5.5. submitted by /u/alice"
    existing = {
        "hash": collect.content_hash(text),
        "modelId": "anthropic/claude-sonnet-5.5",
        "source": "reddit",
        "url": "https://www.reddit.com/r/old/comments/old/old/comment/old/",
        "author": None,
        "postedAt": "2026-09-01T00:00:00Z",
        "text": text,
        "votes": None,
        "judge": None,
    }
    (out_dir / "2026-09-01.jsonl").write_text(
        json.dumps(existing, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    assert run_collect(tmp_path, FakeRunner({SONNET55: make_payload(BASE_RESULTS)})) == 0

    assert len((out_dir / "2026-09-01.jsonl").read_text().splitlines()) == 1
    records = read_today(tmp_path)
    # 跨檔重複（reddit 留言）被跳過，只剩 HN 那筆。
    assert [record["source"] for record in records] == ["hn"]


def test_same_day_rerun_is_idempotent(tmp_path: Path) -> None:
    runner = FakeRunner({SONNET55: make_payload(BASE_RESULTS)})

    assert run_collect(tmp_path, runner) == 0
    first = (tmp_path / "evidence" / f"{TODAY}.jsonl").read_text(encoding="utf-8")
    assert run_collect(tmp_path, runner) == 0
    second = (tmp_path / "evidence" / f"{TODAY}.jsonl").read_text(encoding="utf-8")

    assert first == second


# --- 過濾 -------------------------------------------------------------------


def test_source_whitelist_drops_jobs(tmp_path: Path) -> None:
    run_collect(tmp_path, FakeRunner({SONNET55: make_payload(BASE_RESULTS)}))

    sources = {record["source"] for record in read_today(tmp_path)}
    assert sources <= {"reddit", "hn"}


def test_url_is_required(tmp_path: Path) -> None:
    """缺 url 的結果整筆丟棄。"""
    run_collect(tmp_path, FakeRunner({SONNET55: make_payload(BASE_RESULTS)}))

    records = read_today(tmp_path)
    assert records
    assert all(record["url"] for record in records)
    assert all("without url" not in record["text"] for record in records)


def test_non_english_excluded(tmp_path: Path) -> None:
    run_collect(tmp_path, FakeRunner({SONNET55: make_payload(BASE_RESULTS)}))

    assert all("這個模型很棒" not in record["text"] for record in read_today(tmp_path))


def test_all_records_validate(tmp_path: Path) -> None:
    out_dir = tmp_path / "evidence"
    run_collect(tmp_path, FakeRunner({SONNET55: make_payload(BASE_RESULTS)}))

    assert validate_path(out_dir / f"{TODAY}.jsonl") == []


# --- C9：留言逐則（實作裁定 13）----------------------------------------------


def test_thread_itself_is_not_a_row(tmp_path: Path) -> None:
    """主貼不成 row：只有留言連結落地，url 指向留言永久連結。"""
    run_collect(tmp_path, FakeRunner({SONNET55: make_payload(BASE_RESULTS)}))

    records = read_today(tmp_path)
    assert records
    assert all("/comment/" in record["url"] or "item?id=" in record["url"] for record in records)
    # 主貼的 url 本身不該出現在任何 row 裡。
    assert all(record["url"] != REDDIT_FIRST for record in records)
    assert all(record["url"] != HN_THREAD for record in records)


def test_each_comment_becomes_its_own_row(tmp_path: Path) -> None:
    """一個討論串的多則留言各自成一列，欄位取自留言本身。"""
    comments = {
        ("reddit", REDDIT_FIRST): [
            comment(
                "Sonnet 5.5 coding is strong",
                source="reddit",
                url=f"{REDDIT_FIRST}comment/c1/",
                author="u/alice",
                posted_at="2026-09-23T10:11:12Z",
            ),
            comment(
                "Sonnet 5.5 is slow but accurate",
                source="reddit",
                url=f"{REDDIT_FIRST}comment/c2/",
                author="u/bob",
                posted_at="2026-09-24T10:11:12Z",
            ),
        ]
    }
    run_collect(
        tmp_path,
        FakeRunner({SONNET55: make_payload(BASE_RESULTS[:1])}),
        comment_fetcher=FakeCommentFetcher(comments),
    )

    records = read_today(tmp_path)
    assert len(records) == 2
    assert [record["url"] for record in records] == [
        f"{REDDIT_FIRST}comment/c1/",
        f"{REDDIT_FIRST}comment/c2/",
    ]
    assert [record["author"] for record in records] == ["u/alice", "u/bob"]
    assert [record["postedAt"] for record in records] == [
        "2026-09-23T10:11:12Z",
        "2026-09-24T10:11:12Z",
    ]


def test_thread_without_comments_yields_no_rows(tmp_path: Path) -> None:
    """0 則留言 → 該串不產生資料。"""
    fetcher = FakeCommentFetcher({("reddit", REDDIT_FIRST): []})
    run_collect(
        tmp_path,
        FakeRunner({SONNET55: make_payload(BASE_RESULTS[:1])}),
        comment_fetcher=fetcher,
    )

    assert read_today(tmp_path) == []
    assert fetcher.calls == [("reddit", REDDIT_FIRST)]


def test_comment_fetcher_failure_does_not_abort(tmp_path: Path) -> None:
    """抓留言拋例外 → 該串略過、流程照常完成、退出碼 0。"""

    class Boom:
        def thread_comments(self, *, source: str, url: str, title: str):
            raise RuntimeError("reddit down")

    rc = run_collect(
        tmp_path,
        FakeRunner({SONNET55: make_payload(BASE_RESULTS)}),
        comment_fetcher=Boom(),
    )

    assert rc == 0
    assert read_today(tmp_path) == []


def test_comment_limit_is_ten_per_thread() -> None:
    """每串最多取 10 則留言（enrich.TOP_COMMENTS）。"""
    assert collect.TOP_COMMENTS == 10

    comments = [
        comment(
            f"Sonnet 5.5 take {index}",
            source="reddit",
            url=f"{REDDIT_FIRST}comment/c{index}/",
        )
        for index in range(15)
    ]
    stats = collect.BuildStats()
    model = {"id": "anthropic/claude-sonnet-5.5", "name": SONNET55}
    rows = collect.build_comment_records(
        comments[: collect.TOP_COMMENTS], model, [model], stats, source="reddit"
    )

    assert len(rows) == 10


def test_comment_text_must_mention_model_exactly(tmp_path: Path) -> None:
    """只提品牌字或沒提模型的留言不入池（裁定 14 第 1、2 條）。"""
    comments = {
        ("reddit", REDDIT_FIRST): [
            comment("Claude is great", source="reddit", url="a"),
            comment("This model is great", source="reddit", url="b"),
            comment("Sonnet 4.5 was better", source="reddit", url="c"),
            comment("Sonnet 5.5 is great", source="reddit", url="d"),
        ]
    }
    run_collect(
        tmp_path,
        FakeRunner({SONNET55: make_payload(BASE_RESULTS[:1])}),
        comment_fetcher=FakeCommentFetcher(comments),
    )

    records = read_today(tmp_path)
    assert [record["url"] for record in records] == ["d"]


# --- author 補缺 ------------------------------------------------------------


def test_author_backfilled_from_enricher(tmp_path: Path) -> None:
    """留言自帶 author 時不做補缺；缺 author 才用 enricher 補。"""
    comment_url = f"{REDDIT_FIRST}comment/c1/"
    comments = {
        ("reddit", REDDIT_FIRST): [
            comment("Sonnet 5.5 is great", source="reddit", url=comment_url, author=None)
        ]
    }
    enricher = FakeEnricher(authors={comment_url: "u/alice"})

    run_collect(
        tmp_path,
        FakeRunner({SONNET55: make_payload(BASE_RESULTS[:1])}),
        enricher,
        comment_fetcher=FakeCommentFetcher(comments),
    )

    record = read_today(tmp_path)[0]
    assert record["author"] == "u/alice"


def test_author_null_when_enrichment_fails_and_still_validates(tmp_path: Path) -> None:
    """補齊失敗→author 為 null，且該筆仍通過 schema（實作裁定第 6 條）。"""
    out_dir = tmp_path / "evidence"
    run_collect(
        tmp_path,
        FakeRunner({SONNET55: make_payload(BASE_RESULTS)}),
        comment_fetcher=FakeCommentFetcher(
            {
                ("reddit", REDDIT_FIRST): [
                    comment("Sonnet 5.5 is great", source="reddit", url="a", author=None)
                ]
            }
        ),
    )

    records = read_today(tmp_path)
    assert records
    assert all(record["author"] is None for record in records)
    assert validate_path(out_dir / f"{TODAY}.jsonl") == []
    for record in records:
        EvidenceRecord.model_validate(record)


def test_hn_comment_keeps_its_own_permalink(tmp_path: Path) -> None:
    """HN 留言的 url 必須是留言自己的 item，不被換成討論頁。"""
    comment_url = "https://news.ycombinator.com/item?id=123456"
    enricher = FakeEnricher(urls={comment_url: "https://news.ycombinator.com/item?id=999"})

    run_collect(
        tmp_path,
        FakeRunner({SONNET55: make_payload(BASE_RESULTS[:3])}),
        enricher,
    )

    hn_records = [record for record in read_today(tmp_path) if record["source"] == "hn"]
    assert hn_records
    assert hn_records[0]["url"] == comment_url
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
        comment_fetcher=FakeCommentFetcher(),
        sleep=delays.append,
        now=FIXED_NOW,
    )

    assert rc == 0
    assert runner.calls == 2
    assert delays == [30.0]  # 第一次退避 30s
    assert read_today(tmp_path)  # 重試成功後仍有資料


def test_unreachable_source_warns_but_does_not_abort(tmp_path: Path) -> None:
    status = {"reddit": "ok", "hackernews": "unreachable"}
    runner = FakeRunner({SONNET55: make_payload(BASE_RESULTS, status=status)})
    args = make_args(tmp_path, retries=1, retry_backoff=5.0)

    rc = collect.run(
        args,
        runner=runner,
        enricher=FakeEnricher(),
        comment_fetcher=FakeCommentFetcher(),
        sleep=lambda _s: None,
        now=FIXED_NOW,
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
            "modelId": "anthropic/claude-sonnet-5.5",
            "source": "reddit",
            "url": "https://www.reddit.com/r/x/comments/old/old/comment/old/",
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
        "modelId": "anthropic/claude-sonnet-5.5",
        "source": "reddit",
        "url": "https://www.reddit.com/r/x/comments/new/new/comment/new/",
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
            json={"hits": [{"objectID": "42", "author": "pg", "title": "Sonnet 5.5 review"}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    enricher = HttpEnricher(client=client)

    author, url = enricher.enrich(
        source="hn", url="https://example.com/original", title="Sonnet 5.5 review", text=""
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


# --- C9：留言抓取器（裁定 13）------------------------------------------------


HN_ITEM_JSON = {
    "id": 42,
    "children": [
        {
            "id": 43,
            "author": "alice",
            "created_at": "2026-09-21T10:00:00.000Z",
            "text": "<p>Sonnet 5.5 is great &amp; fast</p>",
            "children": [
                {
                    "id": 44,
                    "author": "bob",
                    "created_at": "2026-09-21T11:00:00.000Z",
                    "text": "<p>Sonnet 5.5 coding is solid</p>",
                    "children": [],
                }
            ],
        },
        {"id": 45, "author": None, "text": "<p>deleted</p>", "children": []},
    ],
}

REDDIT_JSON = [
    {"kind": "Listing", "data": {"children": [{"kind": "t3", "data": {"author": "owner"}}]}},
    {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t1",
                    "data": {
                        "author": "alice",
                        "body": "Sonnet 5.5 wins",
                        "score": 9,
                        "created_utc": 1_789_000_000,
                        "permalink": "/r/x/comments/aaa/slug/c1/",
                    },
                },
                {
                    "kind": "t1",
                    "data": {
                        "author": "bob",
                        "body": "Sonnet 5.5 is fine",
                        "score": 30,
                        "created_utc": 1_789_000_500,
                        "permalink": "/r/x/comments/aaa/slug/c2/",
                    },
                },
                {
                    "kind": "t1",
                    "data": {
                        "author": "bot",
                        "body": "[deleted]",
                        "score": 99,
                        "created_utc": 1_789_000_900,
                        "permalink": "/r/x/comments/aaa/slug/c3/",
                    },
                },
            ]
        },
    },
]

SHREDDIT_HTML = (
    '<shreddit-comment created="2026-09-21T10:00:00.000000+0000" author="alice" '
    'thingId="t1_abc" permalink="/r/x/comments/aaa/slug/c1/" score="5"></shreddit-comment>'
    '<div id="t1_abc-comment-rtjson-content" slot="comment">'
    "<div><p>Sonnet 5.5 wins</p></div></div>"
)


def test_comment_fetcher_reddit_json_sorts_by_score() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=REDDIT_JSON)

    fetcher = HttpCommentFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)))

    comments = fetcher.thread_comments(
        source="reddit", url="https://www.reddit.com/r/x/comments/aaa/slug/", title="t"
    )

    assert [c.url.rsplit("/", 2)[-2] for c in comments] == ["c2", "c1"]
    assert [c.author for c in comments] == ["u/bob", "u/alice"]
    assert comments[0].posted_at.endswith("Z")
    assert fetcher.stats["reddit_json"] == 1


def test_comment_fetcher_falls_back_to_shreddit_on_403() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/.json" in str(request.url):
            return httpx.Response(403, text="blocked")
        return httpx.Response(200, text=SHREDDIT_HTML)

    fetcher = HttpCommentFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)))

    comments = fetcher.thread_comments(
        source="reddit", url="https://www.reddit.com/r/x/comments/aaa/slug/", title="t"
    )

    assert len(comments) == 1
    assert comments[0].author == "u/alice"
    assert comments[0].text == "Sonnet 5.5 wins"
    assert comments[0].url == "https://www.reddit.com/r/x/comments/aaa/slug/c1/"
    assert fetcher.stats["reddit_shreddit"] == 1


def test_comment_fetcher_hn_uses_algolia_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/v1/items/42" in str(request.url)
        return httpx.Response(200, json=HN_ITEM_JSON)

    fetcher = HttpCommentFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)))

    comments = fetcher.thread_comments(
        source="hn", url="https://news.ycombinator.com/item?id=42", title="t"
    )

    # 上層留言優先（depth-first），無作者的留言不採計。
    assert [c.url for c in comments] == [
        "https://news.ycombinator.com/item?id=43",
        "https://news.ycombinator.com/item?id=44",
    ]
    assert comments[0].text == "Sonnet 5.5 is great & fast"  # HTML 去標籤＋解跳脫
    assert comments[0].posted_at == "2026-09-21T10:00:00Z"
    assert fetcher.stats["hn_ok"] == 1


def test_comment_fetcher_caps_at_ten() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": 42,
                "children": [
                    {
                        "id": 100 + index,
                        "author": f"u{index}",
                        "created_at": "2026-09-21T10:00:00.000Z",
                        "text": "<p>Sonnet 5.5 take</p>",
                        "children": [],
                    }
                    for index in range(25)
                ],
            },
        )

    fetcher = HttpCommentFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)))
    comments = fetcher.thread_comments(
        source="hn", url="https://news.ycombinator.com/item?id=42", title="t"
    )

    assert len(comments) == 10


def test_comment_fetcher_unknown_source_returns_empty() -> None:
    fetcher = HttpCommentFetcher(
        client=httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(500)))
    )

    assert fetcher.thread_comments(source="x", url="https://x.com/a/status/1", title="t") == []


# --- 其他單元 ---------------------------------------------------------------


def test_query_uses_model_name_and_default_depth(tmp_path: Path) -> None:
    runner = FakeRunner({SONNET55: make_payload(BASE_RESULTS)})
    run_collect(tmp_path, runner)

    assert runner.calls == [(SONNET55, 30, False)]


def test_deep_flag_is_forwarded(tmp_path: Path) -> None:
    runner = FakeRunner({SONNET55: make_payload(BASE_RESULTS)})
    run_collect(tmp_path, runner, deep=True)

    assert runner.calls[0][2] is True


def test_posted_at_normalized_to_utc_iso(tmp_path: Path) -> None:
    run_collect(tmp_path, FakeRunner({SONNET55: make_payload(BASE_RESULTS)}))

    for record in read_today(tmp_path):
        assert record["postedAt"].endswith("Z")


def test_cli_registers_collect_arguments() -> None:
    parser = build_parser()
    args = parser.parse_args(["collect", "--days", "7", "--models", "GPT-6 Sol"])

    assert args.days == 7
    assert args.models == ["GPT-6 Sol"]
    assert hasattr(args, "output_dir")


# --- X／Twitter 來源 --------------------------------------------------------

# X 列在 agent JSON 的實際形狀（2026-09-29 真抓 engine 輸出）：title 是 summary
# 截斷前 140 字元，url 為 https://x.com/<handle>/status/<id>，無 author 欄位。
X_POST: dict = {
    "source": "x",
    "url": "https://x.com/alice/status/1840000000000000001",
    "published_at": "2026-09-24",
    "title": "Sonnet 5.5 is a joy to use\n\nI love it",
    "summary": "Sonnet 5.5 is a joy to use\n\nI love it a lot. Best model this year.",
}

X_MISSING_URL: dict = {
    "source": "x",
    "published_at": "2026-09-24",
    "title": "Sonnet 5.5 without url",
    "summary": "no permalink on this one",
}

X_NON_ENGLISH: dict = {
    "source": "x",
    "url": "https://x.com/bob/status/1840000000000000002",
    "published_at": "2026-09-23",
    "title": "這個模型很棒",
    "summary": "我很喜歡 Sonnet 5.5 的表現，真的很不錯。",
}


def test_x_post_is_collected_with_author_from_url(tmp_path: Path) -> None:
    """X 列正常轉換：source=x、url 永久連結、author 取自路徑、date 正規化。"""
    runner = FakeRunner({SONNET55: make_payload([X_POST])})

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


def test_x_never_goes_through_comment_fetcher(tmp_path: Path) -> None:
    """X 維持每則推文一筆：不會去抓留言。"""
    fetcher = FakeCommentFetcher()
    run_collect(
        tmp_path,
        FakeRunner({SONNET55: make_payload([X_POST])}),
        comment_fetcher=fetcher,
    )

    assert fetcher.calls == []
    assert len(read_today(tmp_path)) == 1


def test_x_missing_url_dropped(tmp_path: Path) -> None:
    run_collect(tmp_path, FakeRunner({SONNET55: make_payload([X_MISSING_URL])}))

    assert read_today(tmp_path) == []


def test_x_non_english_excluded(tmp_path: Path) -> None:
    run_collect(tmp_path, FakeRunner({SONNET55: make_payload([X_NON_ENGLISH])}))

    assert read_today(tmp_path) == []


def test_x_repost_of_reddit_comment_is_deduplicated(tmp_path: Path) -> None:
    """跨來源同文轉貼：Reddit 留言與 X 轉推同文時只留先到的一筆。"""
    shared_text = "Sonnet 5.5 is a joy to use\nI love Sonnet 5.5. submitted by /u/alice"
    x_repost = {
        "source": "x",
        "url": "https://x.com/alice/status/1840000000000000003",
        "published_at": "2026-09-23",
        "title": "Sonnet 5.5 is a joy to use",
        "summary": shared_text,
    }
    comments = {
        ("reddit", REDDIT_FIRST): [
            comment(shared_text, source="reddit", url=f"{REDDIT_FIRST}comment/c1/")
        ]
    }
    runner = FakeRunner({SONNET55: make_payload([X_POST, x_repost])})

    assert run_collect(
        tmp_path, runner, comment_fetcher=FakeCommentFetcher(comments)
    ) == 0

    records = read_today(tmp_path)
    assert len(records) == 2  # reddit 留言與 X 轉推是不同 url、不同來源


def test_x_author_missing_when_url_is_not_permalink(tmp_path: Path) -> None:
    """url 非標準永久連結時，author 為 null，但該筆仍可落地（schema 允許）。"""
    odd = {
        "source": "x",
        "url": "https://x.com/i/web/status/1840000000000000004",
        "published_at": "2026-09-24",
        "title": "Sonnet 5.5 thoughts",
        "summary": "Sonnet 5.5 thoughts and more.",
    }
    run_collect(tmp_path, FakeRunner({SONNET55: make_payload([odd])}))

    records = read_today(tmp_path)
    assert len(records) == 1
    assert records[0]["author"] is None


def test_x_skipped_unconfigured_warns_and_continues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """無憑證（skipped-unconfigured）：跳過 x、明確警告、其他來源照常、退出碼 0。"""
    status = {"reddit": "ok", "hackernews": "ok", "x": "skipped-unconfigured"}
    runner = FakeRunner({SONNET55: make_payload(BASE_RESULTS, status=status)})
    args = make_args(tmp_path, retries=2, retry_backoff=5.0)

    rc = collect.run(
        args,
        runner=runner,
        enricher=FakeEnricher(),
        comment_fetcher=FakeCommentFetcher(),
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
    summary = "Sonnet 5.5 is a joy to use and the best model I have tried this year."
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
    runner.run(SONNET55, days=30, deep=deep)
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


# --- 歸屬判定（實作裁定 14）-------------------------------------------------

# 測試用的完整清單（含誤歸屬情境：同席的舊版本與別家同世代模型）。
CATALOGUE: list[dict] = [
    {"id": "anthropic/claude-sonnet-5", "name": "Claude Sonnet 5"},
    {"id": "anthropic/claude-sonnet-5.5", "name": "Claude Sonnet 5.5"},
    {"id": "openai/gpt-6-sol", "name": "GPT-6 Sol"},
    {"id": "openai/gpt-6-astra", "name": "GPT-6 Astra"},
    {"id": "openai/gpt-5.6-luna", "name": "GPT-5.6 Luna"},
    {"id": "z-ai/glm-5.3-prime", "name": "GLM 5.3 Prime"},
    {"id": "z-ai/glm-5.3-flash", "name": "GLM 5.3 Flash"},
    {"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
    {"id": "x-ai/grok-4.7", "name": "Grok 4.7"},
    {"id": "moonshotai/kimi-k3", "name": "Kimi K3"},
]
SONNET5 = next(m for m in CATALOGUE if m["id"] == "anthropic/claude-sonnet-5")
GPT6_SOL = next(m for m in CATALOGUE if m["id"] == "openai/gpt-6-sol")
GLM_PRIME = next(m for m in CATALOGUE if m["id"] == "z-ai/glm-5.3-prime")
GLM_FLASH = next(m for m in CATALOGUE if m["id"] == "z-ai/glm-5.3-flash")
GEMINI = next(m for m in CATALOGUE if m["id"] == "google/gemini-2.5-pro")


def engine_result(text: str, slug: str = "post", source: str = "reddit") -> dict:
    url = (
        f"https://www.reddit.com/r/x/comments/{slug}/p/"
        if source == "reddit"
        else f"https://news.ycombinator.com/item?id={slug}"
    )
    return {
        "source": source,
        "url": url,
        "published_at": "2026-09-22",
        "title": text,
        "summary": "",
    }


def classify(text: str, model: dict | None = None) -> collect.Attribution:
    return collect.classify_attribution(text, model or SONNET5, CATALOGUE)


def test_model_keys_are_family_class_version_variant() -> None:
    assert collect.model_keys(SONNET5) == {"anthropic/sonnet/5/-"}
    assert collect.model_keys({"id": "z-ai/glm-5.3-flash", "name": "GLM 5.3 Flash"}) == {
        "zai/-/5.3/flash"
    }
    assert collect.model_keys({"id": "deepseek/deepseek-v4.1-flash", "name": "DeepSeek V4.1 Flash"}) == {
        "deepseek/-/4.1/flash"
    }
    assert collect.model_keys({"id": "qwen/qwen3.8-max-0902", "name": "Qwen3.8 Max"}) == {
        "qwen/-/3.8/max"
    }
    # 沒有版本號的名字不產生鍵（無法做版本精確比對）。
    assert collect.model_keys({"id": "x/y", "name": "Mystery Model"}) == set()


def test_exact_version_kept() -> None:
    for text in ("Claude Sonnet 5 is great", "Sonnet 5 feels fast", "claude-sonnet-5 rocks"):
        assert classify(text).keep, text


def test_other_version_number_is_dropped() -> None:
    """查 Sonnet 5、貼文只提 Sonnet 5.5 → 丟並計入 misattributed（裁定 14 必測）。"""
    verdict = classify("Sonnet 5.5 is a generational leap")

    assert not verdict.keep
    assert verdict.reason == "misattributed"


def test_brand_only_is_dropped() -> None:
    """只提品牌字無版本 → 丟（裁定 14 第 2 條）。"""
    for text in ("Claude is amazing", "Anthropic models are great"):
        verdict = classify(text)
        assert not verdict.keep
        assert verdict.reason == "dropped_brand_only", text


def test_no_mention_is_dropped() -> None:
    """完全沒提模型 → 丟（裁定 14 第 1 條要求每筆 row 都精確提及版本）。"""
    verdict = classify("This model is great and I use it daily")

    assert not verdict.keep
    assert verdict.reason == "dropped_no_mention"


def test_off_catalogue_version_is_dropped() -> None:
    """清單外的家族＋版本（如 Gemini 3.8）→ 丟（裁定 14 第 3 條）。"""
    verdict = classify("Gemini 3.8 just launched")

    assert not verdict.keep
    assert verdict.reason == "misattributed"


def test_multi_model_mention_is_dropped() -> None:
    """同時提及 query 與另一個版本 → 歸屬不明，整筆丟。"""
    verdict = classify("Claude Sonnet 5 vs Sonnet 5.5")

    assert not verdict.keep
    assert verdict.reason == "misattributed"


def test_nickname_must_bind_generation() -> None:
    """暱稱必綁世代：GPT-6 Sol 不吃 GPT-6 Astra、GPT-5.6 Sol（研究報告 §6）。"""
    sol = GPT6_SOL
    assert classify("GPT-6 Sol coding is solid", sol).keep
    for text in ("GPT-6 Astra still leading", "GPT-5.6 Sol expensive", "GPT-6 is here"):
        assert not classify(text, sol).keep, text


def test_variant_suffix_binds_to_generation() -> None:
    """Prime／Flash 只能附掛在對應世代（研究報告 §6）。"""
    prime = GLM_PRIME
    flash = GLM_FLASH
    assert classify("GLM 5.3 Prime value is nuts", prime).keep
    assert classify("GLM 5.3 Flash is cheap", flash).keep
    # 只寫「GLM 5.3」時同世代有兩個變體 → 歸屬不明。
    assert classify("GLM 5.3 is great", prime).reason == "misattributed"
    # 別世代（GLM 5.5）→ 清單外，丟。
    assert classify("GLM 5.5 Flash ships soon", flash).reason == "misattributed"


def test_single_variant_generation_accepts_bare_generation() -> None:
    """同世代只有一席時，社群只寫世代也算命中（例：「Gemini 2.5」）。"""
    gemini = GEMINI
    assert classify("Gemini 2.5 still holds up", gemini).keep
    assert classify("Gemini 2.5 Pro is the best", gemini).keep
    assert classify("Gemini 3 is out", gemini).reason == "misattributed"


def test_x_path_uses_same_attribution_rules() -> None:
    """X 走同一套版本精確比對：查 Sonnet 5 命中不到 Sonnet 5.5 的推文。"""
    stats = collect.BuildStats()
    fetcher = FakeCommentFetcher()
    payload = make_payload(
        [
            dict(X_POST, summary="Sonnet 5.5 is a joy to use"),
            dict(X_MISSING_URL),
        ]
    )

    records = collect.build_records(
        payload, SONNET5, CATALOGUE, stats, comment_fetcher=fetcher
    )

    assert records == []
    assert stats.misattributed == 1
    assert fetcher.calls == []


def test_collect_summary_reports_misattributed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """端到端：誤歸屬的留言不落地，且摘要印出誤歸屬計數。"""
    # 查 Sonnet 5，但留言講的是 Sonnet 5.5 → 誤歸屬，整串不產生資料。
    comments = {
        ("reddit", REDDIT_FIRST): [
            comment("Sonnet 5.5 is a generational leap", source="reddit", url="a")
        ]
    }
    payload = make_payload(BASE_RESULTS[:1])
    payload["query"] = SONNET5_NAME
    runner = FakeRunner({SONNET5_NAME: payload})

    assert (
        run_collect(
            tmp_path,
            runner,
            comment_fetcher=FakeCommentFetcher(comments),
            models=[SONNET5_NAME],
        )
        == 0
    )

    assert read_today(tmp_path) == []
    assert "誤歸屬 1" in capsys.readouterr().out