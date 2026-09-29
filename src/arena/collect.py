"""`arena collect` 的實作（任務 C2）：近 30 天社群貼文收集。

流程（依 ``docs/plan.md`` 的「收集策略」與 ``docs/research/last30days-skill.md``）：

1. 讀 ``config/models.yaml`` 的人工模型清單，對每個模型的 ``name`` 當查詢字串，
   呼叫 vendor 的 ``last30days`` 引擎（``--emit=json --json-profile=agent``，契約
   v1.3，預設 30 天窗口、``--quick``）。
2. **過濾**：只留 ``reddit``／``hackernews``（來源白名單，擋掉 jobs 等雜訊）；
   排除非英文貼文（laya 是英文 checkpoint，見 R1 筆記坑 7）；排除同時提及兩個以上
   模型名的貼文（歸屬不明，見 R1 筆記結尾警告）；缺 url／缺時間的丟棄。
3. **轉換**：``source``（hackernews→hn）、``url``、``postedAt``（ISO）、
   ``text``（title＋summary，截斷至 :data:`MAX_TEXT_CHARS` 字元，理由見證 R1 筆記
   坑 6 的 ~320 token state 預算）、``hash``（正規化文字的 sha256）、``modelId``、
   ``author``；``votes``／``judge`` 一律 ``null``，交給 C3 回填。
4. **補缺**：``author`` 與 HN 討論頁連結以公開 API 回填（見 :mod:`arena.enrich`）；
   失敗留 ``null``，不阻擋。
5. **去重**：與 ``data/evidence/*.jsonl`` 既有的 hash（跨檔）及同批內部都比對，
   重複只留一筆。
6. **落地**：``data/evidence/YYYY-MM-DD.jsonl``（UTC 日期）；同日重跑採
   「讀入→合併去重→原子寫回」，冪等且不留半檔（沿用 ``arena.score`` 的
   mkstemp + ``os.replace`` 手法）。

引擎需要 **Python >= 3.12**，且必須是 vendor 進本 repo 的腳本
（``vendor/last30days/last30days.py``）。執行時優先使用 ``<repo>/.venv/bin/python``，
可用環境變數 ``ARENA_ENGINE_PYTHON`` 覆寫。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from arena.enrich import Enricher, HttpEnricher
from arena.fetch_models import load_manual_models
from arena.schema import EvidenceRecord

EXIT_OK = 0
EXIT_ERROR = 1

# 預設路徑（相對於執行時的工作目錄）。
DEFAULT_MODELS_CONFIG = Path("config/models.yaml")
DEFAULT_OUTPUT_DIR = Path("data/evidence")
DEFAULT_ENGINE_SCRIPT = Path("vendor/last30days/last30days.py")

# 引擎需求（R3 研究筆記「技能身分與可用性」）。
ENGINE_MIN_PYTHON = (3, 12)

# 來源白名單：last30days 的 source → evidence schema 的 source 值。
SOURCE_MAP = {"reddit": "reddit", "hackernews": "hn"}

# 預設時間窗口（天）與抓取模式。
DEFAULT_DAYS = 30

# text 截斷長度（字元）。R1 筆記坑 6：laya 英文 checkpoint 的 state 實際可用
# 約 320 tokens（max_len=512 − head_max_len=192），超過會被靜默截斷。
# 1200 字元是保守值，且 C2 先截斷能讓 C5 用 `--slice tag=long` 單獨量長文子集。
MAX_TEXT_CHARS = 1200

# 非英文貼文的拉丁字母比例門檻（R1 筆記坑 7：英文 checkpoint 對非拉丁文字會崩）。
LATIN_RATIO_MIN = 0.6

# `source_status` 只有這兩個可視為「這輪沒問題」；其餘都不是「沒有討論」。
HEALTHY_STATUSES = {"ok", "no-results"}
# 可以退避重試的失敗狀態（rate-limited 最常見）。
RETRYABLE_STATUSES = {"rate-limited", "timeout", "unreachable", "error", "partial"}

# 引擎呼叫與退避預設值。
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 30.0
DEFAULT_SLEEP_BETWEEN_MODELS_SECONDS = 30.0

# 只補缺「有機會補到」的來源。
_ENRICHABLE_SOURCES = {"reddit", "hn"}

_DIGITS_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_JSON_START_RE = re.compile(r"\{", re.S)


class CollectError(RuntimeError):
    """收集流程中可預期的錯誤（清單問題、引擎缺失、引擎失敗等）。"""


class Runner(Protocol):
    """引擎介面；測試以假物件注入，正式為 :class:`SubprocessRunner`。"""

    def run(self, query: str, *, days: int, deep: bool) -> dict[str, Any]:
        """跑一次引擎並回傳 agent JSON profile 的解析結果。"""
        ...


def _python_version(path: Path) -> tuple[int, int] | None:
    """以子行程問出指定 Python 的版本；失敗回 ``None``。"""
    try:
        proc = subprocess.run(
            [str(path), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        major, minor = proc.stdout.strip().split(".")
        return int(major), int(minor)
    except ValueError:
        return None


def resolve_engine_python(repo_root: Path | None = None) -> Path:
    """決定要用哪個 Python 跑引擎。

    優先序：``ARENA_ENGINE_PYTHON`` → ``<repo>/.venv/bin/python`` → 目前解譯器。
    版本 < 3.12 時丟 :class:`CollectError` 並附可行指令。
    """
    override = os.environ.get("ARENA_ENGINE_PYTHON", "").strip()
    if override:
        candidate = Path(override)
    else:
        venv_python = (repo_root or _repo_root()) / ".venv" / "bin" / "python"
        candidate = venv_python if venv_python.exists() else Path(sys.executable)

    if candidate == Path(sys.executable):
        version = sys.version_info[:2]
    else:
        version = _python_version(candidate)

    if version is None:
        raise CollectError(
            f"無法執行引擎用的 Python：{candidate}\n"
            "  請確認路徑存在，或用 ARENA_ENGINE_PYTHON 指定一個 3.12+ 的 Python。"
        )
    if version < ENGINE_MIN_PYTHON:
        wanted = ".".join(str(part) for part in ENGINE_MIN_PYTHON)
        raise CollectError(
            f"last30days 引擎需要 Python >= {wanted}，目前 {candidate} 是 "
            f"{version[0]}.{version[1]}。\n"
            "  建立 3.12 環境：uv venv .venv --python 3.12\n"
            "  或指定既有解譯器：ARENA_ENGINE_PYTHON=/path/to/python3.12 arena collect"
        )
    return candidate


def _repo_root() -> Path:
    """回傳 repo 根目錄（``src/arena/collect.py`` 往上三層）。"""
    return Path(__file__).resolve().parents[2]


@dataclass
class SubprocessRunner:
    """以子行程呼叫 vendor 引擎的正式 runner。"""

    python: Path
    script: Path
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def create(
        cls,
        *,
        script: Path | None = None,
        repo_root: Path | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> "SubprocessRunner":
        root = repo_root or _repo_root()
        resolved_script = script or (root / DEFAULT_ENGINE_SCRIPT)
        if not resolved_script.exists():
            raise CollectError(
                f"找不到 last30days 引擎：{resolved_script}\n"
                "  請依 vendor/last30days/README.md 重新 vendor（pin commit "
                "084662b501fb0dba95bd55eff0c258d35e0dc499）。"
            )
        return cls(python=resolve_engine_python(root), script=resolved_script, timeout=timeout)

    def run(self, query: str, *, days: int, deep: bool) -> dict[str, Any]:
        command = [
            str(self.python),
            str(self.script),
            query,
            "--emit=json",
            "--json-profile=agent",
            "--days",
            str(days),
        ]
        command.append("--deep" if deep else "--quick")
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise CollectError(f"引擎查詢「{query}」逾時（>{self.timeout:.0f}s）") from exc
        except OSError as exc:
            raise CollectError(f"無法執行引擎：{exc}") from exc

        if proc.returncode != 0:
            detail = _tail(proc.stderr)
            raise CollectError(
                f"引擎查詢「{query}」失敗（exit {proc.returncode}）"
                + (f"：{detail}" if detail else "")
            )
        return _parse_agent_json(proc.stdout, query)


def _parse_agent_json(stdout: str, query: str) -> dict[str, Any]:
    """從引擎 stdout 解析 agent JSON。

    正常情況 stdout 就是一份 JSON；但引擎可能在前後混入少量訊息，故以
    「第一個 ``{`` 到最後一個 ``}``」為候選，解析失敗才報錯。
    """
    text = _ANSI_RE.sub("", stdout).strip()
    candidates = [text]
    if "{" in text and "}" in text:
        candidates.append(text[text.index("{") : text.rindex("}") + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise CollectError(f"引擎查詢「{query}」的 stdout 不是合法 JSON：{_tail(stdout)}")


def _tail(text: str, limit: int = 300) -> str:
    cleaned = " ".join(text.split())
    return cleaned[-limit:] if cleaned else ""


# --- 文字處理 ---------------------------------------------------------------


def normalize_text(text: str) -> str:
    """hash 用的正規化：小寫、連續空白壓成單一空格、去頭尾空白。"""
    return re.sub(r"\s+", " ", text.lower()).strip()


def content_hash(text: str) -> str:
    """正規化文字的 sha256（去重鍵）。"""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def latin_ratio(text: str) -> float:
    """拉丁字母佔全部字母的比例（分母為 0 時回 0.0）。"""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    latin = sum(1 for c in letters if "LATIN" in unicodedata.name(c, ""))
    return latin / len(letters)


def is_probably_english(text: str) -> bool:
    """簡單啟發式：拉丁字母比例達 :data:`LATIN_RATIO_MIN` 才視為英文。"""
    return latin_ratio(text) >= LATIN_RATIO_MIN


def models_mentioned(text: str, model_names: Sequence[str]) -> set[str]:
    """回傳 text 中出現的（設定清單裡的）模型名集合。

    以**詞邊界**比對（大小寫無關），避免「GPT-5」誤命中「GPT-5.6」或「GPT-5.5」
    這類不同版本；模型名本身是整串（可含空白與連字號）。
    """
    return {name for name in model_names if _mention_pattern(name).search(text)}


@lru_cache(maxsize=64)
def _mention_pattern(name: str) -> re.Pattern[str]:
    # 名稱前後不得緊鄰文字字元或小數點，否則視為不同版本。
    return re.compile(r"(?<![\w.])" + re.escape(name) + r"(?![\w.])", re.IGNORECASE)


def compose_text(title: str, summary: str) -> str:
    """把 title 與 summary 合成一段文字（各自 strip、以換行分隔）。

    HN 的 summary 常與 title 完全相同（或更長且已含 title），此時只留一份，
    避免 text 重複而虛耗 laya 的 ~320 token state 預算。
    """
    title = title.strip()
    summary = summary.strip()
    if not summary:
        return title
    if not title:
        return summary
    normalized_title = normalize_text(title)
    normalized_summary = normalize_text(summary)
    if (
        normalized_summary == normalized_title
        or normalized_summary.startswith(normalized_title + " ")
    ):
        return summary
    return f"{title}\n{summary}"


def to_iso(value: Any) -> str | None:
    """把 ``published_at`` 轉成 ``YYYY-MM-DDTHH:MM:SSZ``；無法解析回 ``None``。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if _DIGITS_ONLY_RE.match(text):
        return f"{text}T00:00:00Z"
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- 引擎結果 → evidence 列 -------------------------------------------------


@dataclass
class BuildStats:
    """收集過程的計數，供摘要輸出。"""

    queried: int = 0
    kept: int = 0
    dropped_source: int = 0
    dropped_no_url: int = 0
    dropped_no_date: int = 0
    dropped_non_english: int = 0
    dropped_multi_model: int = 0
    dropped_invalid: int = 0
    duplicates: int = 0
    by_source: dict[str, int] = field(default_factory=dict)

    def note_kept(self, source: str) -> None:
        self.kept += 1
        self.by_source[source] = self.by_source.get(source, 0) + 1


def build_records(
    payload: dict[str, Any],
    model: dict[str, str],
    model_names: Sequence[str],
    stats: BuildStats,
) -> list[dict[str, Any]]:
    """把單一模型的引擎輸出轉成 evidence 列（尚未補缺、去重）。"""
    records: list[dict[str, Any]] = []
    results = payload.get("results")
    if not isinstance(results, list):
        return records

    for result in results:
        if not isinstance(result, dict):
            continue
        raw_source = result.get("source")
        if raw_source not in SOURCE_MAP:
            stats.dropped_source += 1
            continue

        url = str(result.get("url") or "").strip()
        if not url:
            stats.dropped_no_url += 1
            continue

        posted_at = to_iso(result.get("published_at"))
        if posted_at is None:
            stats.dropped_no_date += 1
            continue

        text = compose_text(str(result.get("title") or ""), str(result.get("summary") or ""))
        if not text:
            stats.dropped_no_date += 1
            continue
        if not is_probably_english(text):
            stats.dropped_non_english += 1
            continue
        if len(models_mentioned(text, model_names)) >= 2:
            stats.dropped_multi_model += 1
            continue

        # 截斷到 MAX_TEXT_CHARS（R1 筆記坑 6 的 ~320 token 預算）。
        record = {
            "hash": content_hash(text[:MAX_TEXT_CHARS]),
            "modelId": model["id"],
            "source": SOURCE_MAP[raw_source],
            "url": url,
            "author": None,
            "postedAt": posted_at,
            "text": text[:MAX_TEXT_CHARS],
            # v1.1：未評分時 votes／judge 為 null，交由 C3 `arena score` 回填。
            "votes": None,
            "judge": None,
        }
        records.append(record)
    return records


def _validated(record: dict[str, Any]) -> dict[str, Any] | None:
    """以 schema 驗證一筆記錄；不合法回 ``None``（呼叫端累計後丟棄）。"""
    try:
        parsed = EvidenceRecord.model_validate(record)
    except Exception:  # pydantic.ValidationError
        return None
    return parsed.model_dump(mode="json")


# --- 去重與落地 -------------------------------------------------------------


def load_existing_hashes(output_dir: Path) -> set[str]:
    """掃描 ``output_dir/*.jsonl`` 既有行的 hash（跨檔去重用）。"""
    hashes: set[str] = set()
    if not output_dir.exists():
        return hashes
    for path in sorted(output_dir.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("hash"), str):
                hashes.add(payload["hash"])
    return hashes


def _atomic_write_jsonl(path: Path, lines: Sequence[str]) -> None:
    """原子寫入 jsonl：暫存檔寫在同目錄、fsync 後 ``os.replace``（同 score.py）。"""
    payload = "".join(f"{line}\n" for line in lines)
    directory = path.parent if str(path.parent) else Path(".")
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(directory)
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp 預設 0600；改成一般檔案權限，與 repo 其他資料檔一致。
        os.chmod(temp_path, 0o644)
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def merge_and_write(path: Path, new_records: Sequence[dict[str, Any]]) -> int:
    """把新記錄併入檔案（讀入→去重→原子寫回）；回傳實際新增筆數。"""
    existing_lines: list[str] = []
    existing_hashes: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            existing_lines.append(line)
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("hash"), str):
                existing_hashes.add(payload["hash"])

    added = 0
    for record in new_records:
        if record["hash"] in existing_hashes:
            continue
        existing_hashes.add(record["hash"])
        existing_lines.append(json.dumps(record, ensure_ascii=False))
        added += 1

    _atomic_write_jsonl(path, existing_lines)
    return added


# --- 引擎健康狀態 -----------------------------------------------------------


def unhealthy_sources(status: dict[str, Any]) -> list[tuple[str, str]]:
    """回傳白名單來源中狀態不健康者（``(source, status)``）。"""
    unhealthy: list[tuple[str, str]] = []
    for source in SOURCE_MAP:
        value = status.get(source)
        if isinstance(value, str) and value not in HEALTHY_STATUSES:
            unhealthy.append((source, value))
    return unhealthy


@dataclass
class QueryOutcome:
    """一次（含重試）模型查詢的結果。"""

    payload: dict[str, Any] | None = None
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    final_status: dict[str, Any] = field(default_factory=dict)


def query_model(
    runner: Runner,
    query: str,
    *,
    days: int,
    deep: bool,
    retries: int,
    backoff: float,
    sleep: Callable[[float], None],
) -> QueryOutcome:
    """跑引擎；對可重試的來源狀態退避重試，最後仍失敗則如實回報。"""
    outcome = QueryOutcome()
    attempts = max(1, retries + 1)
    for attempt in range(1, attempts + 1):
        outcome.attempts = attempt
        try:
            payload = runner.run(query, days=days, deep=deep)
        except CollectError as exc:
            outcome.errors.append(str(exc))
            if attempt < attempts:
                sleep(backoff * (2 ** (attempt - 1)))
                continue
            return outcome
        outcome.payload = payload
        status = payload.get("source_status")
        status = status if isinstance(status, dict) else {}
        outcome.final_status = status
        unhealthy = unhealthy_sources(status)
        if not unhealthy:
            return outcome
        retryable = [item for item in unhealthy if item[1] in RETRYABLE_STATUSES]
        outcome.errors.append(
            "來源狀態不健康：" + "、".join(f"{src}={value}" for src, value in unhealthy)
        )
        if not retryable or attempt >= attempts:
            return outcome
        sleep(backoff * (2 ** (attempt - 1)))
    return outcome


# --- 主流程 -----------------------------------------------------------------


def _select_models(models: list[dict], only: Sequence[str] | None) -> list[dict]:
    if not only:
        return models
    wanted = {item.casefold() for item in only}
    selected = [
        model
        for model in models
        if model["id"].casefold() in wanted or model["name"].casefold() in wanted
    ]
    if not selected:
        raise CollectError("--models 指定的模型都不在 config/models.yaml 內：" + ", ".join(only))
    return selected


def _network_allowed() -> bool:
    """預設 runner 是否允許連外。

    `arena collect` 預設會呼叫引擎連網，但測試一律不得連外。`tests/conftest.py`
    的離線防護只涵蓋 fetch-models，因此 collect 自帶一道守門：偵測到 pytest
    （`PYTEST_CURRENT_TEST`）或 `ARENA_OFFLINE` 時，**未注入 runner** 就停手並提示。
    真要連外可設 `ARENA_ALLOW_NETWORK=1`，或直接注入 runner。
    """
    truthy = {"1", "true", "yes", "on"}
    if os.environ.get("ARENA_ALLOW_NETWORK", "").strip().lower() in truthy:
        return True
    if os.environ.get("ARENA_OFFLINE", "").strip().lower() in truthy:
        return False
    return "PYTEST_CURRENT_TEST" not in os.environ


def run(
    args: argparse.Namespace,
    *,
    runner: Runner | None = None,
    enricher: Enricher | None = None,
    sleep: Callable[[float], None] | None = None,
    now: Callable[[], datetime] | None = None,
) -> int:
    """`arena collect` 的進入點。成功回 0（含部分來源退避失敗但有結果）。"""
    sleep = sleep or time.sleep
    now = now or (lambda: datetime.now(timezone.utc))

    config_path = Path(getattr(args, "models_config", None) or DEFAULT_MODELS_CONFIG)
    output_dir = Path(getattr(args, "output_dir", None) or DEFAULT_OUTPUT_DIR)
    days = int(getattr(args, "days", None) or DEFAULT_DAYS)
    deep = bool(getattr(args, "deep", False))
    retries = int(getattr(args, "retries", DEFAULT_RETRIES))
    backoff = float(getattr(args, "retry_backoff", DEFAULT_RETRY_BACKOFF_SECONDS))
    between_models = float(
        getattr(args, "sleep", DEFAULT_SLEEP_BETWEEN_MODELS_SECONDS)
    )

    try:
        all_models = load_manual_models(config_path)
        models = _select_models(all_models, getattr(args, "models", None))
        if runner is None:
            if not _network_allowed():
                print(
                    "arena collect：偵測到離線／測試環境，未注入 runner，已停止以避免連網。\n"
                    "  確定要連網請設 ARENA_ALLOW_NETWORK=1，或注入 runner。",
                    file=sys.stderr,
                )
                return EXIT_ERROR
            runner = SubprocessRunner.create(repo_root=_repo_root())
    except (FileNotFoundError, ValueError, CollectError) as exc:
        print(f"arena collect：{exc}", file=sys.stderr)
        return EXIT_ERROR

    enricher = enricher or HttpEnricher()
    # 多模型混雜判斷用「完整清單」的模型名，即使 --models 只查一部分也一樣。
    model_names = [model["name"] for model in all_models]

    existing_hashes = load_existing_hashes(output_dir)
    seen_hashes = set(existing_hashes)
    stats = BuildStats()
    collected: list[dict[str, Any]] = []
    failures: list[str] = []
    rate_limit_events: list[str] = []

    for index, model in enumerate(models):
        if index and between_models > 0:
            sleep(between_models)
        stats.queried += 1
        outcome = query_model(
            runner,
            model["name"],
            days=days,
            deep=deep,
            retries=retries,
            backoff=backoff,
            sleep=sleep,
        )
        if outcome.payload is None:
            message = outcome.errors[-1] if outcome.errors else "引擎沒有回傳結果"
            failures.append(f"{model['name']}：{message}")
            print(f"  [警告] {model['name']}：{message}", file=sys.stderr)
            continue

        for source, value in unhealthy_sources(outcome.final_status):
            note = f"{model['name']} {source}={value}（重試 {outcome.attempts} 次後）"
            if value == "rate-limited":
                rate_limit_events.append(note)
            else:
                print(f"  [警告] 來源狀態 {note}", file=sys.stderr)

        for record in build_records(outcome.payload, model, model_names, stats):
            if record["hash"] in seen_hashes:
                stats.duplicates += 1
                continue
            seen_hashes.add(record["hash"])
            collected.append(record)

    # 補缺（author／HN 討論頁連結）。
    for record in collected:
        if record["source"] not in _ENRICHABLE_SOURCES:
            continue
        try:
            author, new_url = enricher.enrich(
                source=record["source"],
                url=record["url"],
                title=record["text"].splitlines()[0] if record["text"] else "",
                text=record["text"],
            )
        except Exception as exc:  # 補缺絕不能拖垮主流程
            print(f"  [警告] 補缺失敗（{record['url']}）：{exc}", file=sys.stderr)
            continue
        if author:
            record["author"] = author
        if new_url:
            record["url"] = new_url

    # schema 驗證後才落地；不合法者丟棄（理論上 build_records 已擋掉多半情況）。
    valid: list[dict[str, Any]] = []
    for record in collected:
        cleaned = _validated(record)
        if cleaned is None:
            stats.dropped_invalid += 1
            continue
        valid.append(cleaned)

    output_path = output_dir / f"{now().strftime('%Y-%m-%d')}.jsonl"
    try:
        added = merge_and_write(output_path, valid)
    except OSError as exc:
        print(f"arena collect：無法寫入 {output_path}：{exc}", file=sys.stderr)
        return EXIT_ERROR

    _print_summary(
        output_path=output_path,
        models=models,
        stats=stats,
        added=added,
        failures=failures,
        rate_limit_events=rate_limit_events,
    )
    # 全部模型都查詢失敗才算整體失敗；部分失敗仍回 0（並已在 stderr 警告）。
    if failures and stats.kept == 0 and added == 0:
        return EXIT_ERROR
    return EXIT_OK


def _print_summary(
    *,
    output_path: Path,
    models: list[dict],
    stats: BuildStats,
    added: int,
    failures: list[str],
    rate_limit_events: list[str],
) -> None:
    sources = "、".join(f"{name}={count}" for name, count in sorted(stats.by_source.items()))
    print(
        f"arena collect：查詢 {stats.queried} 個模型"
        f"（{'、'.join(model['name'] for model in models)}），"
        f"寫入 {output_path} 新增 {added} 筆。"
    )
    print(
        "  過濾：來源不符 {dropped_source}、缺 url {dropped_no_url}、"
        "缺時間/空文 {dropped_no_date}、非英文 {dropped_non_english}、"
        "多模型 {dropped_multi_model}、schema 不合法 {dropped_invalid}；"
        "重複（含跨檔／同批）{duplicates}。".format(**stats.__dict__)
    )
    if stats.kept:
        print(f"  本輪保留 {stats.kept} 筆（{sources}），實際新增 {added} 筆。")
    if rate_limit_events:
        print(f"  [警告] 被限流：{'；'.join(rate_limit_events)}", file=sys.stderr)
    if failures:
        print(f"  [警告] {len(failures)} 個模型查詢失敗：{'；'.join(failures)}", file=sys.stderr)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """把 collect 的參數掛上 argparse 子解析器（cli.py 會自動呼叫）。"""
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"抓取窗口天數（預設 {DEFAULT_DAYS}）",
    )
    parser.add_argument(
        "--models",
        nargs="*",
        default=None,
        metavar="MODEL",
        help="只收集這些模型（id 或 name；預設 config/models.yaml 全部）",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=f"evidence 輸出目錄（預設 {DEFAULT_OUTPUT_DIR}）",
    )
    parser.add_argument(
        "--models-config",
        default=None,
        help=f"模型清單路徑（預設 {DEFAULT_MODELS_CONFIG}）",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="用引擎的 --deep 高召回模式（預設 --quick）",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_BETWEEN_MODELS_SECONDS,
        help=f"模型之間的間隔秒數，避免 keyless Reddit 限流（預設 {DEFAULT_SLEEP_BETWEEN_MODELS_SECONDS:.0f}）",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help=f"來源失敗時的重試次數（預設 {DEFAULT_RETRIES}）",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=DEFAULT_RETRY_BACKOFF_SECONDS,
        help=f"退避重試的初始秒數，逐次加倍（預設 {DEFAULT_RETRY_BACKOFF_SECONDS:.0f}）",
    )


__all__ = [
    "BuildStats",
    "CollectError",
    "DEFAULT_DAYS",
    "DEFAULT_ENGINE_SCRIPT",
    "DEFAULT_MODELS_CONFIG",
    "DEFAULT_OUTPUT_DIR",
    "EXIT_ERROR",
    "EXIT_OK",
    "HttpEnricher",
    "LATIN_RATIO_MIN",
    "MAX_TEXT_CHARS",
    "QueryOutcome",
    "SOURCE_MAP",
    "SubprocessRunner",
    "add_arguments",
    "build_records",
    "compose_text",
    "content_hash",
    "is_probably_english",
    "latin_ratio",
    "load_existing_hashes",
    "merge_and_write",
    "models_mentioned",
    "normalize_text",
    "query_model",
    "resolve_engine_python",
    "run",
    "to_iso",
    "unhealthy_sources",
]
