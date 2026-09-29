"""C2 的補缺模組：以公開 API 回填 evidence 的 ``author`` 與 HN 討論頁連結。

背景（見 ``docs/research/last30days-skill.md`` 第 112 行起）：

- `last30days` 的 agent JSON profile（v1.3）**沒有 ``author`` 欄位**，
  所以 C2 落地時必須自行補齊；補不到就留 ``null``，不能讓整個收集流程失敗。
- HN 結果的 ``url`` 多半指向**外部原文**，不是 HN 討論頁；用 Algolia API
  （免 key）以標題查回 ``news.ycombinator.com/item?id=...`` 當永久連結。
- Reddit 貼文的 ``url`` 已是永久連結；作者可用公開 JSON
  ``https://www.reddit.com/comments/<id>/.json`` 的 ``author`` 欄補齊，
  但 keyless 路徑常被擋（本環境實測 403）；此外 Reddit 摘要偶爾含
  ``submitted by /u/<name>``，可先做零網路的字串擷取。

設計：

- :class:`Enricher` 是介面，測試以假物件注入；正式為 :class:`HttpEnricher`。
- 任何單筆補缺失敗都只回 ``(None, None)`` 並累計統計，**不丟例外**、不阻擋主流程。
- Reddit 作者統一存成 ``u/<name>``（與種子資料 ``data/evidence/sample.jsonl`` 一致），
  HN 作者存裸使用者名（Algolia 原樣）。
"""

from __future__ import annotations

import re
from typing import Any, Protocol
from urllib.parse import quote

import httpx

# 公開、免 key 的補缺端點。
REDDIT_JSON_TEMPLATE = "https://www.reddit.com/comments/{id}/.json"
HN_ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search"

# Reddit 要求可辨識的 User-Agent；HN Algolia 不挑。
DEFAULT_USER_AGENT = "llm-arena-collect/0.1 (+https://github.com/jason-lab/llm-arena)"

# Reddit 永久連結中的貼文 id：``/comments/<id>/``。
_REDDIT_ID_RE = re.compile(r"/comments/([A-Za-z0-9]+)")
# 摘要裡常見的 ``submitted by /u/<name>``。
_REDDIT_AUTHOR_RE = re.compile(r"/u/([A-Za-z0-9_-]{2,})")

# 單筆補缺結果：(author, 取代用的 url)。兩者都可能為 None（＝不需要／失敗）。
EnrichResult = tuple[str | None, str | None]


class Enricher(Protocol):
    """補缺介面；`collect` 以注入方式使用，測試提供假物件。"""

    def enrich(self, *, source: str, url: str, title: str, text: str) -> EnrichResult:
        """回傳 ``(author, new_url)``；無新資訊時該項為 ``None``。"""
        ...


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
    "DEFAULT_USER_AGENT",
    "EnrichResult",
    "Enricher",
    "HttpEnricher",
    "HN_ALGOLIA_SEARCH",
    "REDDIT_JSON_TEMPLATE",
]
