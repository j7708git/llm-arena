"""C2 的補缺模組：以公開 API 回填 evidence 的 ``author`` 與 HN 討論頁連結。

C9 起另含「留言逐則」抓取（實作裁定 13，見 :class:`HttpCommentFetcher`）。

背景（見 ``docs/research/last30days-skill.md`` 第 112 行起）：

- `last30days` 的 agent JSON profile（v1.3）**沒有 ``author`` 欄位**，
  所以 C2 落地時必須自行補齊；補不到就留 ``null``，不能讓整個收集流程失敗。
- HN 結果的 ``url`` 多半指向**外部原文**，不是 HN 討論頁；用 Algolia API
  （免 key）以標題查回 ``news.ycombinator.com/item?id=...`` 當永久連結。
- Reddit 貼文的 ``url`` 已是永久連結；作者可用公開 JSON
  ``https://www.reddit.com/comments/<id>/.json`` 的 ``author`` 欄補齊，
  但 keyless 路徑常被擋（本環境實測 403）；此外 Reddit 摘要偶爾含
  ``submitted by /u/<name>``，可先做零網路的字串擷取。

C9（實作裁定 13「留言逐則」）新增的 :class:`HttpCommentFetcher`：

- Reddit 每個討論串取熱門前 :data:`TOP_COMMENTS` 則**留言**（裁定 15 由 10 提到 20）。
  優先走規格上的
  ``.../comments/<id>/.json``；**本環境實測 keyless 一律 403**（2026-10-01，
  換 UA／old.reddit／api.reddit 都一樣），故 fallback 到 Reddit 仍免 key 開放的
  shreddit 留言端點 ``/svc/shreddit/comments/r/<sub>/t3_<id>``（回 HTML，留言內嵌為
  ``<shreddit-comment>`` 元素，已實測 200）。兩條路徑都解析成同一個結構。
- HN 每個討論串取前 :data:`TOP_COMMENTS` 則**留言**，資料源是 Algolia
  ``/api/v1/items/<id>``（免 key，實測 200）。**HN 不公開留言分數**，故依
  Algolia 回傳的樹狀順序（depth-first、上層留言優先）取前 N 則（N 為
  :data:`TOP_COMMENTS`，裁定 15 提到 20），此點已如實記錄於
  ``docs/progress-status.md``。
- 兩來源的留言都轉成 :class:`ThreadComment`（``url``＝留言永久連結、
  ``author``＝留言者、``postedAt``＝留言時間、``text``＝去標籤後的留言原文）。

設計：

- :class:`Enricher` 是介面，測試以假物件注入；正式為 :class:`HttpEnricher`。
- 任何單筆補缺失敗都只回 ``(None, None)`` 並累計統計，**不丟例外**、不阻擋主流程。
- Reddit 作者統一存成 ``u/<name>``（與種子資料 ``data/samples/evidence.sample.jsonl`` 一致），
  HN 作者存裸使用者名（Algolia 原樣）。
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import quote

import httpx

# 公開、免 key 的補缺端點。
REDDIT_JSON_TEMPLATE = "https://www.reddit.com/comments/{id}/.json"
HN_ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search"
HN_ALGOLIA_ITEM = "https://hn.algolia.com/api/v1/items/{id}"

# C9：每個討論串取的熱門留言數（實作裁定 13）；裁定 15 由 10 提到 20。
# Reddit 依 score 排序取前 N；HN 無公開分數，依 Algolia 樹狀順序取前 N。
TOP_COMMENTS = 20

# Reddit 要求可辨識的 User-Agent；HN Algolia 不挑。
DEFAULT_USER_AGENT = "llm-arena-collect/0.1 (+https://github.com/jason-lab/llm-arena)"

# Reddit 永久連結中的貼文 id：``/comments/<id>/``。
_REDDIT_ID_RE = re.compile(r"/comments/([A-Za-z0-9]+)")
# 摘要裡常見的 ``submitted by /u/<name>``。
_REDDIT_AUTHOR_RE = re.compile(r"/u/([A-Za-z0-9_-]{2,})")
# shreddit 端點需要 subreddit 名與貼文 id：``/r/<sub>/comments/<id>/``。
_REDDIT_REF_RE = re.compile(r"/r/([A-Za-z0-9_]+)/comments/([A-Za-z0-9]+)")
# HN 永久連結的 item id：``news.ycombinator.com/item?id=<id>``。
_HN_ITEM_ID_RE = re.compile(r"[?&]id=(\d+)")
# shreddit 留言元素起始標籤（含屬性）；不含 comment-tree 等別的元素。
_SHREDDIT_COMMENT_RE = re.compile(r"<shreddit-comment(?=[\s>])[^>]*>")
# 留言正文容器：``<div id="<thingId>-comment-rtjson-content" slot="comment">``。
_SHREDDIT_BODY_RE = re.compile(
    r'id="(?:t1_[A-Za-z0-9]+)-comment-rtjson-content"[^>]*>(.*?)</div>\s*</div>',
    re.S,
)
_SHREDDIT_ATTR_RE = re.compile(r'([A-Za-z-]+)="([^"]*)"')
_TAG_RE = re.compile(r"<[^>]+>")
# 被刪除／被移除／機器人（bot、AutoModerator 類）留言不採計。
_BOT_AUTHOR_RE = re.compile(r"bot$|^AutoModerator$", re.IGNORECASE)


def _reddit_post_id(url: str) -> str | None:
    match = _REDDIT_ID_RE.search(url or "")
    return match.group(1) if match else None


def _reddit_shreddit_ref(url: str) -> tuple[str, str] | None:
    match = _REDDIT_REF_RE.search(url or "")
    return (match.group(1), match.group(2)) if match else None


def _hn_object_id(url: str) -> str | None:
    match = _HN_ITEM_ID_RE.search(url or "")
    return match.group(1) if match else None


def _hn_object_id_from_title(client: httpx.Client, title: str) -> str | None:
    """HN 結果的 url 常指向外部原文；用標題回查 discussion 頁的 item id。"""
    if not title.strip():
        return None
    params = {"query": title[:200], "tags": "story", "hitsPerPage": "5"}
    try:
        response = client.get(HN_ALGOLIA_SEARCH, params=params)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        hits = response.json().get("hits", [])
    except (ValueError, AttributeError):
        return None
    for hit in hits:
        if isinstance(hit, dict) and _normalize_title(str(hit.get("title", ""))) == (
            _normalize_title(title)
        ):
            object_id = hit.get("objectID")
            return object_id if isinstance(object_id, str) and object_id else None
    return None


def _to_iso(value: Any) -> str | None:
    """把 Reddit ``created_utc``（epoch 秒）或 ISO 字串轉成 ``...Z``。"""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


def _strip_html(fragment: str) -> str:
    """把留言的 HTML 去標籤、反跳脫、壓空白（Reddit／HN 留言都是 HTML 片段）。"""
    text = _TAG_RE.sub(" ", fragment or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _author_or_none(author: Any) -> str | None:
    if not isinstance(author, str):
        return None
    name = author.strip()
    if not name or name in {"[deleted]", "[removed]"} or _BOT_AUTHOR_RE.search(name):
        return None
    return name


def _reddit_json_rows(children: Any) -> list[ThreadComment]:
    """``comments/<id>/.json`` 的留言列（依 score 排序後取前 N，於呼叫端截斷）。"""
    rows: list[tuple[int, ThreadComment]] = []
    if not isinstance(children, list):
        return []
    for child in children:
        if not isinstance(child, dict) or child.get("kind") != "t1":
            continue
        data = child.get("data")
        if not isinstance(data, dict):
            continue
        body = data.get("body")
        text = body.strip() if isinstance(body, str) else ""
        if not text or text in {"[deleted]", "[removed]"}:
            continue
        permalink = data.get("permalink")
        if not isinstance(permalink, str) or not permalink:
            continue
        author = _author_or_none(data.get("author"))
        rows.append(
            (
                int(data.get("score") or 0),
                ThreadComment(
                    url=f"https://www.reddit.com{permalink}",
                    author=f"u/{author}" if author else None,
                    posted_at=_to_iso(data.get("created_utc")),
                    text=text,
                ),
            )
        )
    rows.sort(key=lambda row: row[0], reverse=True)
    return [comment for _score, comment in rows]


def _parse_shreddit_comments(html_text: str) -> list[ThreadComment]:
    """解析 shreddit 留言 HTML：每個 ``<shreddit-comment>`` 一則（依 score 排序）。"""
    bodies: dict[str, str] = {}
    for match in _SHREDDIT_BODY_RE.finditer(html_text or ""):
        key = match.group(0).split('id="', 1)[-1].split("-comment-rtjson-content", 1)[0]
        bodies[key] = match.group(1)

    rows: list[tuple[int, ThreadComment]] = []
    for match in _SHREDDIT_COMMENT_RE.finditer(html_text or ""):
        attrs = dict(_SHREDDIT_ATTR_RE.findall(match.group(0)))
        thing_id = attrs.get("thingId") or ""
        body = bodies.get(thing_id)
        text = _strip_html(body) if body else ""
        if not text:
            continue
        author = _author_or_none(attrs.get("author"))
        permalink = attrs.get("permalink") or ""
        if not permalink:
            continue
        try:
            score = int(attrs.get("score") or 0)
        except ValueError:
            score = 0
        rows.append(
            (
                score,
                ThreadComment(
                    url=f"https://www.reddit.com{permalink}",
                    author=f"u/{author}" if author else None,
                    posted_at=_to_iso(attrs.get("created")),
                    text=text,
                ),
            )
        )
    rows.sort(key=lambda row: row[0], reverse=True)
    return [comment for _score, comment in rows]


def _hn_comment_rows(children: Any, story_id: str, depth: int = 0) -> list[ThreadComment]:
    """Algolia ``items/<id>`` 的留言樹：depth-first、上層優先。

    HN 不公開留言分數，無從依熱門排序，故依 Algolia 回傳的樹狀順序取前 N。
    """
    if not isinstance(children, list) or depth > 3:
        return []
    rows: list[ThreadComment] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        text = _strip_html(child.get("text"))
        author = _author_or_none(child.get("author"))
        if text and author:
            object_id = child.get("id")
            comment_url = (
                f"https://news.ycombinator.com/item?id={object_id}"
                if isinstance(object_id, (str, int)) and str(object_id)
                else f"https://news.ycombinator.com/item?id={story_id}"
            )
            rows.append(
                ThreadComment(
                    url=comment_url,
                    author=author,
                    posted_at=_to_iso(child.get("created_at")),
                    text=text,
                )
            )
        rows.extend(_hn_comment_rows(child.get("children"), story_id, depth + 1))
    return rows

# 單筆補缺結果：(author, 取代用的 url)。兩者都可能為 None（＝不需要／失敗）。
EnrichResult = tuple[str | None, str | None]


class Enricher(Protocol):
    """補缺介面；`collect` 以注入方式使用，測試提供假物件。"""

    def enrich(self, *, source: str, url: str, title: str, text: str) -> EnrichResult:
        """回傳 ``(author, new_url)``；無新資訊時該項為 ``None``。"""
        ...


@dataclass(frozen=True)
class ThreadComment:
    """一則留言（C9 的 evidence「一筆」）。

    欄位語意與 evidence schema 完全對應：``url`` 是留言的永久連結、
    ``author`` 是留言者、``postedAt`` 是留言時間、``text`` 是留言原文。
    """

    url: str
    author: str | None
    posted_at: str | None
    text: str


class CommentFetcher(Protocol):
    """留言抓取介面；`collect` 以注入方式使用，測試提供假物件。

    :meth:`thread_url` 是**選用**能力（裁定 15 要把主貼永久連結寫進 evidence 的
    ``thread.url``）：Reddit 的引擎結果 url 本身就是永久連結，HN 的 url 常指向外部
    原文，需回查 Algolia 拿 ``news.ycombinator.com/item?id=...``。測試注入的假抓取器
    沒有實作它時，`collect` 直接沿用原 url。
    """

    def thread_comments(self, *, source: str, url: str, title: str) -> list[ThreadComment]:
        """回傳該討論串的熱門留言；抓不到／無留言時回空清單（不丟例外）。"""
        ...


class HttpCommentFetcher:
    """以 httpx 抓 Reddit／HN 每串熱門留言（實作裁定 13）。

    Reddit 走兩段式：先試規格上的 ``.json``，403（本環境實測）時退到仍免 key
    開放的 shreddit 留言 HTML 端點。HN 走 Algolia ``items/<id>``。
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: float = 20.0,
        limit: int = TOP_COMMENTS,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
        )
        self._limit = limit
        # 標題回查的結果快取：thread_url 與 thread_comments 共用，避免同一串查兩次。
        self._hn_item_ids: dict[str, str | None] = {}
        # 統計供 run() 回報；鍵名固定方便測試。
        self.stats: dict[str, int] = {
            "reddit_json": 0,
            "reddit_shreddit": 0,
            "reddit_failed": 0,
            "hn_ok": 0,
            "hn_failed": 0,
        }

    def thread_url(self, *, source: str, url: str, title: str) -> str:
        """回傳主貼的永久連結（裁定 15 的 ``thread.url``）。查不到就沿用原 url。"""
        if source != "hn":
            return url
        object_id = self._hn_item_id(url, title)
        return f"https://news.ycombinator.com/item?id={object_id}" if object_id else url

    def thread_comments(
        self, *, source: str, url: str, title: str
    ) -> list[ThreadComment]:
        if source == "reddit":
            comments = self._reddit_comments(url)
        elif source == "hn":
            comments = self._hn_comments(url, title)
        else:
            return []
        # 熱門前 N 則（Reddit 已按分數排序；HN 依樹狀順序，見模組 docstring）。
        # 裁定 15：N 由 10 提到 20。
        return comments[: self._limit]

    # --- Reddit -----------------------------------------------------------

    def _reddit_comments(self, url: str) -> list[ThreadComment]:
        post_id = _reddit_post_id(url)
        if post_id is None:
            self.stats["reddit_failed"] += 1
            return []
        comments = self._reddit_json_comments(post_id)
        if comments:
            self.stats["reddit_json"] += 1
            return comments
        comments = self._reddit_shreddit_comments(url)
        if comments:
            self.stats["reddit_shreddit"] += 1
            return comments
        self.stats["reddit_failed"] += 1
        return []

    def _reddit_json_comments(self, post_id: str) -> list[ThreadComment]:
        endpoint = REDDIT_JSON_TEMPLATE.format(id=quote(post_id))
        try:
            response = self._client.get(endpoint, params={"limit": "100"})
        except httpx.HTTPError:
            return []
        if response.status_code != 200:
            return []
        try:
            payload: Any = response.json()
            listing = payload[1]["data"]["children"]
        except (ValueError, KeyError, IndexError, TypeError):
            return []
        return _reddit_json_rows(listing)

    def _reddit_shreddit_comments(self, url: str) -> list[ThreadComment]:
        ref = _reddit_shreddit_ref(url)
        if ref is None:
            return []
        subreddit, post_id = ref
        endpoint = (
            f"https://www.reddit.com/svc/shreddit/comments/r/{subreddit}/t3_{post_id}"
        )
        try:
            response = self._client.get(endpoint, headers={"Accept": "text/html"})
        except httpx.HTTPError:
            return []
        if response.status_code != 200:
            return []
        return _parse_shreddit_comments(response.text)

    # --- Hacker News ------------------------------------------------------

    def _hn_item_id(self, url: str, title: str) -> str | None:
        """HN story 的 item id：優先 url 上的 id，否則用標題回查（結果快取）。"""
        cached = self._hn_item_ids.get(url)
        if cached is not None:
            return cached or None
        object_id = _hn_object_id(url) or _hn_object_id_from_title(self._client, title)
        self._hn_item_ids[url] = object_id or ""
        return object_id

    def _hn_comments(self, url: str, title: str) -> list[ThreadComment]:
        object_id = self._hn_item_id(url, title)
        if object_id is None:
            self.stats["hn_failed"] += 1
            return []
        try:
            response = self._client.get(HN_ALGOLIA_ITEM.format(id=quote(object_id)))
        except httpx.HTTPError:
            self.stats["hn_failed"] += 1
            return []
        if response.status_code != 200:
            self.stats["hn_failed"] += 1
            return []
        try:
            payload: Any = response.json()
        except ValueError:
            self.stats["hn_failed"] += 1
            return []
        comments = _hn_comment_rows(payload.get("children"), object_id)
        if not comments:
            self.stats["hn_failed"] += 1
            return []
        self.stats["hn_ok"] += 1
        return comments


class HttpEnricher:
    """以 httpx 呼叫 Reddit／Algolia 的正式補缺器。"""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: float = 20.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
        )
        # 統計供 run() 回報；鍵名固定方便測試。
        self.stats: dict[str, int] = {
            "reddit_from_text": 0,
            "reddit_from_json": 0,
            "reddit_failed": 0,
            "hn_ok": 0,
            "hn_failed": 0,
        }

    def enrich(self, *, source: str, url: str, title: str, text: str) -> EnrichResult:
        if source == "reddit":
            return self._enrich_reddit(url, text), None
        if source == "hn":
            return self._enrich_hn(title)
        return None, None

    # --- Reddit -----------------------------------------------------------

    def _enrich_reddit(self, url: str, text: str) -> str | None:
        # 先做零成本的摘要擷取，避免無謂的網路請求。
        match = _REDDIT_AUTHOR_RE.search(text)
        if match:
            self.stats["reddit_from_text"] += 1
            return f"u/{match.group(1)}"

        reddit_id = self._reddit_id(url)
        if reddit_id is None:
            self.stats["reddit_failed"] += 1
            return None

        author = self._reddit_author(reddit_id)
        if author:
            self.stats["reddit_from_json"] += 1
            return f"u/{author}"
        self.stats["reddit_failed"] += 1
        return None

    @staticmethod
    def _reddit_id(url: str) -> str | None:
        match = _REDDIT_ID_RE.search(url)
        return match.group(1) if match else None

    def _reddit_author(self, reddit_id: str) -> str | None:
        endpoint = REDDIT_JSON_TEMPLATE.format(id=quote(reddit_id))
        try:
            response = self._client.get(endpoint)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            payload: Any = response.json()
            author = payload[0]["data"]["children"][0]["data"].get("author")
        except (ValueError, KeyError, IndexError, TypeError):
            return None
        if isinstance(author, str) and author.strip() and author != "[deleted]":
            return author.strip()
        return None

    # --- Hacker News ------------------------------------------------------

    def _enrich_hn(self, title: str) -> EnrichResult:
        if not title.strip():
            self.stats["hn_failed"] += 1
            return None, None
        params = {
            "query": title[:200],
            "tags": "story",
            "hitsPerPage": "5",
        }
        try:
            response = self._client.get(HN_ALGOLIA_SEARCH, params=params)
        except httpx.HTTPError:
            self.stats["hn_failed"] += 1
            return None, None
        if response.status_code != 200:
            self.stats["hn_failed"] += 1
            return None, None
        try:
            hits = response.json().get("hits", [])
        except (ValueError, AttributeError):
            self.stats["hn_failed"] += 1
            return None, None

        hit = self._pick_hn_hit(hits, title)
        if hit is None:
            self.stats["hn_failed"] += 1
            return None, None

        object_id = hit.get("objectID")
        if not isinstance(object_id, str) or not object_id:
            self.stats["hn_failed"] += 1
            return None, None

        author = hit.get("author")
        author = author.strip() if isinstance(author, str) and author.strip() else None
        self.stats["hn_ok"] += 1
        return author, f"https://news.ycombinator.com/item?id={object_id}"

    @staticmethod
    def _pick_hn_hit(hits: list[Any], title: str) -> dict[str, Any] | None:
        """優先挑標題（大小寫、空白正規化後）完全相同者，否則取第一筆。"""
        normalized = _normalize_title(title)
        for hit in hits:
            if isinstance(hit, dict) and _normalize_title(str(hit.get("title", ""))) == normalized:
                return hit
        for hit in hits:
            if isinstance(hit, dict):
                return hit
        return None


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


__all__ = [
    "CommentFetcher",
    "DEFAULT_USER_AGENT",
    "EnrichResult",
    "Enricher",
    "HN_ALGOLIA_ITEM",
    "HN_ALGOLIA_SEARCH",
    "HttpCommentFetcher",
    "HttpEnricher",
    "REDDIT_JSON_TEMPLATE",
    "ThreadComment",
    "TOP_COMMENTS",
]
