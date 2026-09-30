"""`arena score` 的 LLM 評審團實作（任務 C8）。

契約以 ``docs/plan.md``「Schema 實作裁定」第 12 條為準：

- 四位評審（`JURY_MEMBERS`）**獨立呼叫**：同一 prompt、同一 rubric（沿用
  :data:`arena.score.QUESTION` 的六題）、JSON 輸出、溫度 0，不得互看。
- 前三家用 OpenRouter ``:batch`` 變體（半價、非同步、24h 內回）；``qwen3.7-flash``
  為 owner 指定的觀察員、無 batch 版，一律原價。
- 每面向取多數；``prob`` ＝同票比例（3/4=0.75、4/4=1.0）；**2/4 平手 → 該面向
  ``label``／``prob`` 記 null**（視同資料不足，build 自動排除）。
- ``juryVotes`` 逐票保留（鍵＝成員短名，失敗的成員記 null）；
  ``judge`` ＝ ``llm-jury@<membersHash 前 8 碼>``（members 排序後以 ``\\n`` 串接的 sha256）。
- 429／逾時指數退避重試 ≤3 次，仍失敗 → 該筆 evidence 的 ``votes`` 記 null
  （下次重跑會自動重試），並於 stderr 統計。

HTTP 一律走 ``httpx``；測試以 ``httpx.MockTransport`` 注入 ``transport``，
或直接注入假的 ``client``，**不打真網路**。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import httpx

from arena.schema import OVERALL_VOTE_ID, VOTE_IDS
from arena.score import QUESTION, Prediction, ScoreError, Vote

# --- 評審團名單（實作裁定 12）-----------------------------------------------

# 評審成員（base id）；前三家走 `:batch`、qwen 為 owner 指定觀察員（無 batch 版）。
# 評審團成員。歷史：C8 初版為四人（deepseek/glm/gpt-6-luna/qwen3.7）多數決；
# 2026-10-01 owner 裁定收斂為單一評審 qwen3.7-flash（gold v2 上 0.852 並列第一、
# 過 0.80 門檻；成本 4→1）。多數決機制保留——未來要擴編只需改這裡。
JURY_MEMBERS: tuple[str, ...] = ("qwen/qwen3.7-flash",)
# 沒有 `:batch` 變體的成員：任何模式都用原價同步版。
NON_BATCH_MEMBERS: frozenset[str] = frozenset({"qwen/qwen3.7-flash"})
BATCH_SUFFIX = ":batch"

# 面向允許的標籤（overall 用三類態度，五個面向多了 not-discussed）。
_OVERALL_LABELS: tuple[str, ...] = ("positive", "negative", "neutral")
_FACET_LABELS: tuple[str, ...] = ("positive", "negative", "not-discussed")

# OpenRouter 端點與重試參數。
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT = 120.0
# 429／逾時最多重試次數（含首次共 4 次嘗試）；指數退避 1、2、4 秒。
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 1.0
# batch 輪詢間隔與整體時限（OpenRouter batch window 為 24h）。
DEFAULT_POLL_INTERVAL_SECONDS = 10.0
DEFAULT_BATCH_TIMEOUT_SECONDS = 24 * 60 * 60

_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_TERMINAL_BATCH_STATUSES = frozenset({"completed", "failed", "expired", "cancelled"})

# 剛建立的 batch 有同步延遲：GET /batches/{id} 會先回 404，之後才查得到。
# wait_batch 在這個寬限期內把 404 當「尚未可見」繼續輪詢；超過仍 404 視為真錯誤。
BATCH_NOT_FOUND_GRACE_SECONDS = 600.0

# API key 環境變數（缺 key 明確報錯，不靜默降級）。
API_KEY_ENV = "OPENROUTER_API_KEY"

SYSTEM_PROMPT = (
    "You are a strict, impartial annotation judge for a dataset that measures "
    "community sentiment about AI models. Read the social-media post and classify "
    "the attitude of its author. Judge only what the author expresses: never use "
    "your own opinion, the post's popularity, or outside knowledge. Answer every "
    "question with exactly one of the allowed labels. Respond with a single valid "
    "JSON object and nothing else."
)


class JuryCallError(ScoreError):
    """單一評審呼叫在重試後仍失敗（429／逾時／非預期回應）。"""


# --- 成員識別與 prompt -------------------------------------------------------


def member_short_name(member: str) -> str:
    """成員短名（``juryVotes`` 的鍵）：member id 的 ``/`` 後段。"""
    return member.rsplit("/", 1)[-1]


def members_hash(members: Sequence[str] = JURY_MEMBERS) -> str:
    """members 排序後以 ``\\n`` 串接的 sha256（十六進位）。"""
    joined = "\n".join(sorted(members))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def jury_judge(members: Sequence[str] = JURY_MEMBERS) -> str:
    """judge 欄位：``llm-jury@<membersHash 前 8 碼>``。"""
    return f"llm-jury@{members_hash(members)[:8]}"


def api_model_id(member: str, *, use_batch: bool) -> str:
    """實際送 OpenRouter 的模型 id（batch 模式且該成員有 batch 版才加 ``:batch``）。"""
    if use_batch and member not in NON_BATCH_MEMBERS:
        return f"{member}{BATCH_SUFFIX}"
    return member


def _allowed_labels(facet: str) -> tuple[str, ...]:
    return _OVERALL_LABELS if facet == OVERALL_VOTE_ID else _FACET_LABELS


def _questions_block() -> str:
    """把 :data:`arena.score.QUESTION` 六題（同 laya rubric）攤成文字。"""
    blocks: list[str] = []
    for facet, spec in QUESTION.items():
        lines = [f"- {facet}: {spec['instructions']}"]
        for label in _allowed_labels(facet):
            lines.append(f"    * {label}: {spec['criteria'][label]}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def build_messages(post_text: str) -> list[dict[str, str]]:
    """組出送評的 chat messages：**只放貼文文字**，不含 modelId／模型名。

    六題題目本身就要求判作者對貼文中所談模型的態度，但 state 不放模型名，
    避免評審自我偏袒（沿用 laya 版的原則）。
    """
    json_hint = "{" + ", ".join(f'"{facet}": "..."' for facet in VOTE_IDS) + "}"
    user = (
        "Classify the attitude expressed in the post below.\n\n"
        "Rules:\n"
        "- Answer all six questions, each with exactly one allowed label.\n"
        '- "not-discussed" means the post does not discuss that aspect, or mentions '
        "it without evaluating it.\n"
        "- Judge only the post's author; ignore whether you agree with them.\n\n"
        "Questions:\n"
        f"{_questions_block()}\n\n"
        "POST (verbatim):\n"
        '"""\n'
        f"{post_text}\n"
        '"""\n\n'
        "Reply with ONLY a JSON object (no markdown fences, no prose) with exactly "
        f"these keys:\n{json_hint}\n"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _loads_json_object(content: str) -> dict[str, Any]:
    """把模型回覆解析成 JSON 物件；容忍 ```json code fence 與前後綴文字。"""
    text = content.strip()
    if text.startswith("```"):
        # 去掉開頭的 ```json／``` 與結尾的 ```
        text = text.split("\n", 1)[1] if "\n" in text else ""
        stripped = text.rstrip()
        if stripped.endswith("```"):
            text = stripped[:-3]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("回覆不是 JSON 物件") from None
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("回覆不是 JSON 物件")
    return parsed


def parse_member_labels(content: str) -> dict[str, str | None]:
    """解析單一成員對六題的回覆。

    回傳六鍵（`VOTE_IDS`）；缺漏或不在允許清單的標籤記 ``None``（該面向視為沒投）。
    整份不是合法 JSON 物件時丟 :class:`ValueError`。
    """
    parsed = _loads_json_object(content)
    return {
        facet: (parsed.get(facet) if parsed.get(facet) in _allowed_labels(facet) else None)
        for facet in VOTE_IDS
    }


# --- 聚合 ---------------------------------------------------------------------


@dataclass(frozen=True)
class JuryOutcome:
    """聚合結果：``votes`` 為 None 代表該則整體作廢（有成員呼叫失敗）。"""

    votes: dict[str, Vote] | None
    jury_votes: dict[str, dict[str, str | None]]


def _member_label(result: Mapping[str, str | None] | None, facet: str) -> str | None:
    if result is None:
        return None
    return result.get(facet)


def aggregate_member_labels(
    per_member: Mapping[str, Mapping[str, str | None] | None],
    members: Sequence[str] = JURY_MEMBERS,
) -> JuryOutcome:
    """把各成員的六題標籤聚合成多數決結果（實作裁定 12）。

    - 任一成員為 ``None``（呼叫失敗）→ 整則 ``votes=None``，但 ``jury_votes``
      仍保留各成員的票（失敗者各面向為 null）供稽核。
    - 每面向取多數；``prob`` ＝得票數／有效票數；沒有唯一最高票（含 2/2 平手、
      四票分散）→ 該面向 label／prob 皆 null。
    """
    jury_votes = {
        facet: {
            member_short_name(member): _member_label(per_member.get(member), facet)
            for member in members
        }
        for facet in VOTE_IDS
    }

    if any(per_member.get(member) is None for member in members):
        return JuryOutcome(votes=None, jury_votes=jury_votes)

    votes: dict[str, Vote] = {}
    for facet in VOTE_IDS:
        tally: dict[str, int] = {}
        for member in members:
            label = _member_label(per_member.get(member), facet)
            if label is not None:
                tally[label] = tally.get(label, 0) + 1
        total = sum(tally.values())
        if total == 0:
            votes[facet] = Vote(None, None)
            continue
        best = max(tally.values())
        winners = [label for label, count in tally.items() if count == best]
        votes[facet] = (
            Vote(winners[0], best / total) if len(winners) == 1 else Vote(None, None)
        )

    return JuryOutcome(votes=votes, jury_votes=jury_votes)


# --- OpenRouter 客戶端 --------------------------------------------------------


def _chat_body(model: str, messages: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    """同步與 batch 共用的 chat/completions 請求 body（溫度 0、強制 JSON）。"""
    return {
        "model": model,
        "messages": list(messages),
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }


class OpenRouterChatClient:
    """OpenRouter ``chat/completions`` 與 Batch API 的極簡客戶端。

    ``transport``／``sleep``／``clock`` 可注入，測試全程離線且不必真的等待。
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ScoreError(
                f"缺少 {API_KEY_ENV}；arena score 需要 OpenRouter API key 才能呼叫評審團，"
                "不得靜默降級。"
            )
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.transport = transport
        self.sleep = sleep
        self.clock = clock

    # -- 低階請求（含重試） ------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        last: object = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                    response = client.request(method, url, headers=self._headers(), **kwargs)
            except httpx.HTTPError as exc:  # 逾時與網路錯誤
                last = exc
            else:
                if response.status_code in _RETRYABLE_STATUS:
                    last = f"HTTP {response.status_code}"
                elif response.status_code >= 400:
                    raise JuryCallError(f"{method} {url} 失敗：HTTP {response.status_code}")
                else:
                    return response
            if attempt < self.max_retries:
                self.sleep(self.backoff_seconds * (2**attempt))
        raise JuryCallError(f"{method} {url} 重試 {self.max_retries} 次後仍失敗：{last}")

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise JuryCallError(f"回應不是 JSON：{exc}") from exc
        if not isinstance(payload, dict):
            raise JuryCallError("回應不是 JSON 物件")
        return payload

    @staticmethod
    def _content(payload: dict[str, Any]) -> str:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise JuryCallError(f"回應缺少 choices[0].message.content：{exc}") from exc
        if not isinstance(content, str) or not content.strip():
            raise JuryCallError("回應內容為空")
        return content

    # -- 同步 chat/completions --------------------------------------------
    def chat_completion(self, model: str, messages: Sequence[Mapping[str, str]]) -> str:
        response = self._request(
            "POST", "/chat/completions", json=_chat_body(model, messages)
        )
        return self._content(self._json(response))

    # -- 非同步 Batch API --------------------------------------------------
    def submit_batch(self, model: str, requests: Sequence[Mapping[str, Any]]) -> str:
        body = {
            "endpoint": "/v1/chat/completions",
            "model": model,
            "requests": list(requests),
        }
        payload = self._json(self._request("POST", "/batches", json=body))
        batch_id = payload.get("id")
        if not isinstance(batch_id, str) or not batch_id:
            raise JuryCallError("batch 回應缺少 id")
        return batch_id

    def wait_batch(
        self,
        batch_id: str,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        timeout: float = DEFAULT_BATCH_TIMEOUT_SECONDS,
    ) -> list[Any]:
        deadline = self.clock() + timeout
        grace_deadline = self.clock() + BATCH_NOT_FOUND_GRACE_SECONDS
        while True:
            try:
                payload = self._json(self._request("GET", f"/batches/{batch_id}"))
            except JuryCallError as exc:
                # 剛建立的 batch 尚未同步到查詢端（404）：寬限期內繼續等。
                if "HTTP 404" in str(exc) and self.clock() < grace_deadline:
                    self.sleep(poll_interval)
                    continue
                raise
            status = payload.get("status")
            if status in _TERMINAL_BATCH_STATUSES:
                results = payload.get("results")
                return results if isinstance(results, list) else []
            if self.clock() >= deadline:
                raise JuryCallError(f"batch {batch_id} 逾時（status={status}）")
            self.sleep(poll_interval)

    @staticmethod
    def _batch_content(item: Any) -> str | None:
        """從一筆 batch result 取回覆內容；該筆失敗（error／非 200）回 None。"""
        if not isinstance(item, dict) or item.get("error"):
            return None
        response = item.get("response")
        if not isinstance(response, dict):
            return None
        status = response.get("status_code")
        if status is not None and status != 200:
            return None
        body = response.get("body")
        if not isinstance(body, dict):
            return None
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        return content if isinstance(content, str) and content.strip() else None


# --- 預測器 -------------------------------------------------------------------


class JuryPredictor:
    """四位評審獨立呼叫同一 prompt，再聚合；實作 :class:`arena.score.Predictor`。"""

    def __init__(
        self,
        client: OpenRouterChatClient,
        *,
        members: Sequence[str] = JURY_MEMBERS,
        use_batch: bool = True,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        batch_timeout: float = DEFAULT_BATCH_TIMEOUT_SECONDS,
        sync_workers: int = 8,
    ) -> None:
        self.client = client
        self.members = tuple(members)
        self.use_batch = use_batch
        self.poll_interval = poll_interval
        self.batch_timeout = batch_timeout
        self.sync_workers = max(1, sync_workers)
        self.judge = jury_judge(self.members)
        self.stats: dict[str, int] = {
            "member_failures": 0,
            "posts_failed": 0,
            "invalid_facets": 0,
        }
        # 保留最後幾筆失敗原因（只進 stderr 報告，不進資料檔）。
        self.last_errors: list[str] = []

    # -- 對外介面 ---------------------------------------------------------
    def classify(self, states: list[dict[str, str]]) -> list[Prediction]:
        messages = [build_messages(state["post"]) for state in states]
        per_state: list[dict[str, Mapping[str, str | None] | None]] = [
            {} for _ in states
        ]

        if self.use_batch:
            self._classify_batch(messages, per_state)
        else:
            self._classify_sync(messages, per_state)

        predictions: list[Prediction] = []
        for raw in per_state:
            outcome = aggregate_member_labels(raw, self.members)
            if outcome.votes is None:
                self.stats["posts_failed"] += 1
            predictions.append(
                Prediction(votes=outcome.votes, jury_votes=outcome.jury_votes)
            )
        return predictions

    def failure_report(self) -> str | None:
        """有失敗時回一段 stderr 統計字串；全數成功回 None。"""
        if not any(self.stats.values()):
            return None
        report = (
            "arena score：評審呼叫失敗 {member_failures} 次，受影響貼文 "
            "{posts_failed} 則（votes 記 null，重跑會自動重試）；"
            "無效／缺漏的面向回覆 {invalid_facets} 個。"
        ).format(**self.stats)
        if self.last_errors:
            report += " 最後一筆錯誤：" + self.last_errors[-1]
        return report

    # -- 內部 -------------------------------------------------------------
    def _record_parse(self, labels: Mapping[str, str | None]) -> None:
        self.stats["invalid_facets"] += sum(1 for value in labels.values() if value is None)

    def _classify_sync(
        self,
        messages: Sequence[Sequence[Mapping[str, str]]],
        per_state: list[dict[str, Mapping[str, str | None] | None]],
    ) -> None:
        with ThreadPoolExecutor(max_workers=self.sync_workers) as pool:
            for member in self.members:
                self._sync_member(member, messages, per_state, pool=pool)

    def _sync_member(
        self,
        member: str,
        messages: Sequence[Sequence[Mapping[str, str]]],
        per_state: list[dict[str, Mapping[str, str | None] | None]],
        *,
        pool: ThreadPoolExecutor | None = None,
    ) -> None:
        """單一成員的同步逐則呼叫（``_classify_sync`` 與 batch 模式的退回路徑共用）。

        ``pool`` 提供時逐則並行（I/O bound；推理模型單呼叫可達數十秒，
        序列跑 216 則要數小時——2026-09-30 owner 因速度裁定改並行）。
        """
        model = api_model_id(member, use_batch=False)

        def work(index: int) -> tuple[int, dict[str, str | None] | None, str | None]:
            try:
                content = self.client.chat_completion(model, messages[index])
                return index, parse_member_labels(content), None
            except (JuryCallError, ValueError) as exc:
                return index, None, str(exc)

        if pool is not None:
            results = list(pool.map(work, range(len(messages))))
        else:
            results = [work(index) for index in range(len(messages))]

        for index, labels, error in results:
            if labels is None:
                self.stats["member_failures"] += 1
                if error:
                    self.last_errors.append(f"[{member}] p{index}: {error}")
                per_state[index][member] = None
                continue
            self._record_parse(labels)
            per_state[index][member] = labels

    def _classify_batch(
        self,
        messages: Sequence[Sequence[Mapping[str, str]]],
        per_state: list[dict[str, Mapping[str, str | None] | None]],
    ) -> None:
        for member in self.members:
            if member in NON_BATCH_MEMBERS:
                # 該成員沒有 :batch 端點（批次 API 對無 batch 版模型回 400），
                # 退回同步呼叫（OpenRouter ChatClient 會自動重試 429/5xx）。
                self._sync_member(member, messages, per_state)
                continue
            model = api_model_id(member, use_batch=True)
            requests = [
                {"custom_id": f"p{index}", "body": _chat_body(model, message)}
                for index, message in enumerate(messages)
            ]
            try:
                batch_id = self.client.submit_batch(model, requests)
                results = self.client.wait_batch(
                    batch_id,
                    poll_interval=self.poll_interval,
                    timeout=self.batch_timeout,
                )
            except JuryCallError as exc:
                # 整個 batch 掛掉：該成員對所有貼文記失敗（保留原因供 stderr）。
                self.stats["member_failures"] += len(messages)
                self.last_errors.append(f"[{member}] {exc}")
                for index in range(len(messages)):
                    per_state[index][member] = None
                continue

            by_id: dict[str, Any] = {}
            for item in results:
                if isinstance(item, dict) and isinstance(item.get("custom_id"), str):
                    by_id[item["custom_id"]] = item

            for index in range(len(messages)):
                content = self.client._batch_content(by_id.get(f"p{index}"))
                if content is None:
                    self.stats["member_failures"] += 1
                    per_state[index][member] = None
                    continue
                try:
                    labels = parse_member_labels(content)
                except ValueError:
                    self.stats["member_failures"] += 1
                    per_state[index][member] = None
                    continue
                self._record_parse(labels)
                per_state[index][member] = labels


def build_jury_predictor(*, use_batch: bool) -> JuryPredictor:
    """由環境變數組出正式評審團預測器；缺 ``OPENROUTER_API_KEY`` 時明確報錯。"""
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        raise ScoreError(
            f"缺少 {API_KEY_ENV} 環境變數；arena score 需要 OpenRouter API key "
            "才能呼叫評審團（不靜默降級）。請先 "
            f"`export {API_KEY_ENV}=sk-or-...`。"
        )
    return JuryPredictor(OpenRouterChatClient(api_key), use_batch=use_batch)


__all__ = [
    "API_KEY_ENV",
    "BATCH_SUFFIX",
    "DEFAULT_BACKOFF_SECONDS",
    "DEFAULT_BASE_URL",
    "DEFAULT_BATCH_TIMEOUT_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_TIMEOUT",
    "JURY_MEMBERS",
    "JuryCallError",
    "JuryOutcome",
    "JuryPredictor",
    "NON_BATCH_MEMBERS",
    "OpenRouterChatClient",
    "SYSTEM_PROMPT",
    "aggregate_member_labels",
    "api_model_id",
    "build_jury_predictor",
    "build_messages",
    "jury_judge",
    "member_short_name",
    "members_hash",
    "parse_member_labels",
]
