"""`arena score` 的實作：**C8 起以 OpenRouter 四人 LLM 評審團**對 evidence 逐則投票。

C8（2026-09-30）後 `arena score` 的預設 judge 是 LLM 評審團，實作在
:mod:`arena.jury`（成員、聚合、重試、batch 都照 ``docs/plan.md`` 實作裁定第 12 條）；
本模組保留評分流程骨架（掃描、跳過已評分、原子寫入）與 laya 版的 :class:`LayaPredictor`
（**已淘汰，見下**，僅留在 git 歷史供回溯與舊測試）。

評分流程：送評的 state **只放貼文文字**（不放 modelId／模型名，避免評分器自我偏袒）；
回填 ``votes``（多數決聚合；2/4 平手該面向記 null）、``juryVotes``（逐票）與
``judge``（``llm-jury@<hash>``）。輸出採**原子寫入**：先寫同目錄暫存檔、fsync 後以
``os.replace`` 覆蓋；過程中任何例外都不會留下半截 jsonl。已有 ``votes`` 的行會被跳過
（冪等），``force`` 為真時才重評。

C3 的 laya 實作（設計與用法見 ``docs/research/jev-scoring.md``）保留在此，
標記為 DEPRECATED；其 schema v1.1 欄位語意以 ``docs/plan.md``「資料契約」
與實作裁定 7~9 為準：

- 模型：``convaiinnovations/laya`` 英文 checkpoint，pin revision
  ``55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851``（筆記「具體選型參數」）。
- 題型：**一次 pass 問六題**，每題都是三選項 ``choice``（仍落在 ``choice:3-5``
  溫度 bucket）。``overall`` 沿用原本的總評題（positive／negative／neutral）；
  五個面向題的標籤是 positive／negative／``not-discussed``（「貼文未談該面向，
  或談了但沒有評價立場」）；identical 的 third option 是 not-discussed。
- 校準機率用 ``answer_confidence``（＝``max(p)``），**不是** ``confidence``。
- 六題結果以 ``votes``（六鍵）回填，``judge`` 寫 ``laya@55cf4c4``。
- 固定 ``batch_size``：laya 同 process 重跑確定，但 batch 大小不同會有微浮點差
  （筆記「已知坑」第 9 條）。
- ``USE_TF=0``、預設 ``LAYA_DEVICE=cpu``（筆記「已知坑」第 11 條、「具體選型參數」）。

CLI 參數：``cli.py`` 解凍後會呼叫 :func:`add_arguments`，掛上 ``files`` 位置參數、
``--force`` 與 ``--batch``（非同步半價版；**預設為同步呼叫**）。另支援環境變數：

- ``ARENA_EVIDENCE_FILES``：以 ``:`` 分隔的 evidence 檔清單（預設 ``data/evidence/*.jsonl``）。
- ``ARENA_SCORE_FORCE``：設為 1/true/yes 時等同 ``--force``。
- ``ARENA_SCORE_NO_BATCH``：設為 1/true/yes 時強制同步（蓋過 ``--batch``）。
- ``OPENROUTER_API_KEY``：評審團 API key；**缺 key 時明確報錯，不得靜默降級**。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

from arena.schema import OVERALL_VOTE_ID, VOTE_IDS

# 必須在 transformers 被匯入前設定：環境同時安裝 TensorFlow 時，
# transformers 匯入期探測 TF 可能造成 abseil deadlock（R1 筆記「已知坑」第 11 條）。
os.environ.setdefault("USE_TF", "0")
# 本機無 GPU，預設 CPU。注意 `laya.load()` 本身不讀 LAYA_DEVICE（那是 laya-serve 用的），
# 所以下面仍會把 device 明確傳給 load；這裡設環境變數是為了子行程／一致性。
os.environ.setdefault("LAYA_DEVICE", "cpu")

EXIT_OK = 0
EXIT_ERROR = 1

# 模型與評分常數（R1 筆記「具體選型參數」）。
# DEPRECATED（C8，2026-09-30）：laya 在 gold 上 0.4424、domain fit 問題，score 已改接
# LLM 評審團（arena.jury）。以下常數與 LayaPredictor 保留供回溯與舊測試，勿用於新流程。
MODEL_ID = "convaiinnovations/laya"
REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
JUDGE = "laya@55cf4c4"
# overall（總評）題的 id；沿用 v1 的命名，作為 votes 的第一鍵。
QUESTION_ID = OVERALL_VOTE_ID

# 固定 batch size：laya 官方明載 batch 大小不同可能造成微小浮點差，
# 會讓決策在門檻邊緣翻面；C3 的「可重現」要求固定此值（R1 筆記「已知坑」第 9 條）。
DEFAULT_BATCH_SIZE = 8

# `arena score` 未指定檔案時掃描的預設路徑。
DEFAULT_EVIDENCE_GLOB = "data/evidence/*.jsonl"

# 一次 pass 六題：overall（總評）＋五個面向維度，每題都是三選項 choice。
# 選項標籤刻意使用語意字（不是 true/false、yes/no），官方明載模型可能跟標籤走
# （R1 筆記「已知坑」第 4 條）。題目文字不得出現任何模型名（state 只有貼文）。
#
# 五個面向題的第三選項一律是 `not-discussed`：貼文未談該面向，或談了但沒有
# 評價立場。`neutral` 只屬於 overall；`not-discussed` 不適用於 overall
# （plan.md 實作裁定第 8 條）。
QUESTION: dict[str, dict[str, Any]] = {
    "overall": {
        "type": "choice",
        "instructions": (
            "What is the author's overall attitude toward the AI model discussed in this post?"
        ),
        "criteria": {
            "positive": "The author praises the model, recommends it, or is clearly satisfied.",
            "negative": (
                "The author criticises the model, complains about it, or prefers an alternative."
            ),
            "neutral": (
                "The author states a fact, asks a question, or has no clear positive "
                "or negative stance."
            ),
        },
    },
    "quality": {
        "type": "choice",
        "instructions": (
            "What is the author's attitude toward the model's capability and output "
            "quality (correctness, intelligence, reliability)?"
        ),
        "criteria": {
            "positive": (
                "The author praises the model's capability or output quality, or considers "
                "it correct, smart, or reliable."
            ),
            "negative": (
                "The author criticises the model's capability, correctness, intelligence, "
                "or reliability."
            ),
            "not-discussed": (
                "The post does not discuss the model's capability or output quality, or "
                "mentions it without evaluating it."
            ),
        },
    },
    "speed": {
        "type": "choice",
        "instructions": (
            "What is the author's attitude toward the model's response speed, latency, "
            "or throughput?"
        ),
        "criteria": {
            "positive": "The author praises the model as fast, responsive, or high-throughput.",
            "negative": "The author criticises the model as slow, laggy, or low-throughput.",
            "not-discussed": (
                "The post does not discuss the model's response speed or latency, or "
                "mentions it without evaluating it."
            ),
        },
    },
    "tokenEfficiency": {
        "type": "choice",
        "instructions": (
            "What is the author's attitude toward how concisely the model answers and how "
            "efficiently it uses context and tokens?"
        ),
        "criteria": {
            "positive": (
                "The author praises the model for being concise or for using context and "
                "tokens efficiently."
            ),
            "negative": (
                "The author criticises the model for being verbose, rambling, or wasteful "
                "with context or tokens."
            ),
            "not-discussed": (
                "The post does not discuss the model's verbosity or context/token "
                "efficiency, or mentions it without evaluating it."
            ),
        },
    },
    "tokenUsage": {
        "type": "choice",
        "instructions": (
            "What is the author's attitude toward how many tokens (or how much of a usage "
            "quota) the model consumes to complete tasks?"
        ),
        "criteria": {
            "positive": (
                "The author praises the model for consuming few tokens or for being light "
                "on usage limits."
            ),
            "negative": (
                "The author criticises the model for consuming many tokens or for draining "
                "usage limits quickly."
            ),
            "not-discussed": (
                "The post does not discuss how many tokens or how much quota the model "
                "consumes, or mentions it without evaluating it."
            ),
        },
    },
    "priceValue": {
        "type": "choice",
        "instructions": (
            "What is the author's attitude toward the model's price and value for money "
            "(API pricing, subscription cost, or free-tier value)?"
        ),
        "criteria": {
            "positive": "The author considers the model cheap, affordable, or good value.",
            "negative": "The author considers the model expensive, overpriced, or poor value.",
            "not-discussed": (
                "The post does not discuss the model's price or value for money, or "
                "mentions it without evaluating it."
            ),
        },
    },
}

# 題目鍵必須與 schema 的 votes 鍵集合一致，否則回填會缺鍵／多鍵。
assert tuple(QUESTION) == VOTE_IDS, "QUESTION 的題目鍵必須等於 schema 的 VOTE_IDS"


class ScoreError(RuntimeError):
    """評分流程中可預期的錯誤（檔案問題、laya 未安裝、預測器回傳不符等）。"""


@dataclass(frozen=True)
class Vote:
    """單一題目的投票：標籤 + 機率。

    C8 起兩者允許同時為 ``None``：代表該面向在評審團聚合後 2/4 平手
    （視同資料不足）；laya 版永遠有值。
    """

    label: str | None
    prob: float | None


@dataclass(frozen=True)
class Prediction:
    """單則貼文的六題結果（鍵為 `VOTE_IDS`）。

    ``votes`` 為 None 代表整則作廢（有評審呼叫失敗）；``jury_votes`` 為逐位評審的
    原始票（鍵：面向 → 成員短名 → 標籤或 null），laya 版為 None。
    """

    votes: dict[str, Vote] | None
    jury_votes: dict[str, dict[str, str | None]] | None = None


class Predictor(Protocol):
    """評分器介面；正式為 :class:`arena.jury.JuryPredictor`（測試以假物件注入）。

    :class:`LayaPredictor` 是 C3 的舊實作（DEPRECATED），仍符合此介面。
    """

    def classify(self, states: list[dict[str, str]]) -> list[Prediction]:
        """對一批 state（每筆為 ``{"post": text}``）回傳對齊順序的預測。"""
        ...


def build_state(record: dict[str, Any]) -> dict[str, str]:
    """組出送評的 state：**只放貼文文字**，不放 modelId／模型名（遮蔽自我偏袒）。

    evidence schema 只有 ``text`` 一欄（R1 筆記提到的 title+summary 由 C2 併入 text）。
    """
    return {"post": record["text"]}


class LayaPredictor:
    """以 ``laya.load`` 載入的評分器（CPU 可跑、零 output token）。

    **DEPRECATED（C8）**：score 已改用 :class:`arena.jury.JuryPredictor`；本類別保留
    供回溯與舊測試，正常流程不會再建立它。
    """

    # `arena score` 回填 evidence 的 judge 字串（laya 短 sha）。
    judge: str = JUDGE

    def __init__(self, agent: Any, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        self.agent = agent
        self.batch_size = batch_size

    @classmethod
    def load(
        cls,
        device: str | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        revision: str = REVISION,
    ) -> "LayaPredictor":
        """載入 laya 英文 checkpoint（首次會下載 ~842 MB）。"""
        try:
            import laya
        except ImportError as exc:  # pragma: no cover - 只在未安裝 laya 時觸發
            raise ScoreError(
                "無法匯入 laya；請先安裝評分相依（CPU 版 torch 很大，請耐心等）：\n"
                '  uv pip install --python .venv/bin/python -e ".[score,dev]" --torch-backend=cpu'
            ) from exc

        resolved_device = device or os.environ.get("LAYA_DEVICE") or "cpu"

        # 溫度：本程式**不覆寫**任何 temperature_by_options，直接沿用出廠值。
        # 我們的三選項題落在 `choice:3-5` bucket，出廠溫度 1.7602 是有效的。
        # 若 C5 的 ECE 未達標，依 R1 筆記「步驟 4：不達標時的溫度縮放」在另一份
        # held-out 標註集上重新擬合後，於此處注入（值域須維持 [0.5, 5.0]）：
        #     agent.temperature_by_options["choice:3-5"] = T
        # 這是會影響所有歷史分數的參數；一旦更動必須重跑 `arena score` 並發新資料。
        agent = laya.load(MODEL_ID, device=resolved_device, revision=revision)
        return cls(agent, batch_size=batch_size)

    def classify(self, states: list[dict[str, str]]) -> list[Prediction]:
        results = self.agent.predict_batch(states, QUESTION, batch_size=self.batch_size)
        predictions: list[Prediction] = []
        for result in results:
            answers = result["answers"]
            votes = {
                # 校準機率一律用 answer_confidence（=max(p)），不是 confidence。
                qid: Vote(
                    label=str(answers[qid]["choice"]),
                    prob=float(answers[qid]["answer_confidence"]),
                )
                for qid in QUESTION
            }
            predictions.append(Prediction(votes=votes))
        return predictions


@dataclass
class _FileWork:
    """單一 evidence 檔的解析結果：原始行與對應的 record（空白行為 None）。"""

    path: Path
    lines: list[str]
    records: list[dict[str, Any] | None]


@dataclass(frozen=True)
class _Task:
    """一則待評分的貼文。"""

    file_index: int
    line_index: int
    state: dict[str, str]


def _load_file(path: Path) -> _FileWork:
    """讀入一個 evidence jsonl；JSON 壞掉時丟 :class:`ScoreError`（不寫檔）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScoreError(f"{path}：無法讀取檔案：{exc}") from exc

    lines = text.splitlines()
    records: list[dict[str, Any] | None] = []
    for number, raw in enumerate(lines, start=1):
        if not raw.strip():
            records.append(None)
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ScoreError(f"{path} 第 {number} 行：JSON 解析失敗：{exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ScoreError(f"{path} 第 {number} 行：每行必須是 JSON 物件")
        records.append(payload)
    return _FileWork(path=path, lines=lines, records=records)


def _is_scored(record: dict[str, Any]) -> bool:
    """已評分的定義：``votes`` 非 null（v1.1；v1 的 label 已移除）。"""
    return record.get("votes") is not None


def _collect_tasks(plans: Sequence[_FileWork], force: bool) -> list[_Task]:
    """挑出需要評分的行；force 為真時全部重評，否則跳過已有 votes 的行（冪等）。"""
    tasks: list[_Task] = []
    for file_index, plan in enumerate(plans):
        for line_index, record in enumerate(plan.records):
            if record is None:
                continue
            if not force and _is_scored(record):
                continue
            text = record.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ScoreError(f"{plan.path} 第 {line_index + 1} 行：缺少可評分的 text")
            tasks.append(
                _Task(file_index=file_index, line_index=line_index, state=build_state(record))
            )
    return tasks


def _atomic_write_jsonl(path: Path, lines: Sequence[str]) -> None:
    """原子寫入 jsonl：暫存檔寫在同目錄、fsync 後 ``os.replace`` 覆蓋原檔。"""
    payload = "".join(f"{line}\n" for line in lines)
    directory = path.parent if str(path.parent) else Path(".")
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(directory)
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _apply(
    plans: Sequence[_FileWork],
    tasks: Sequence[_Task],
    predictor: Predictor,
) -> int:
    """呼叫預測器回填 votes／juryVotes／judge，並以原子寫入保存有變動的檔案。"""
    predictions = predictor.classify([task.state for task in tasks])
    if len(predictions) != len(tasks):
        raise ScoreError(
            f"預測器回傳 {len(predictions)} 筆，與輸入 {len(tasks)} 筆不符"
        )

    # judge 由預測器決定（評審團＝llm-jury@<hash>；laya 版＝laya@<sha>）。
    judge = getattr(predictor, "judge", JUDGE)

    expected_ids = set(QUESTION)
    changed: dict[int, set[int]] = {}
    for task, prediction in zip(tasks, predictions):
        plan = plans[task.file_index]
        votes_payload: dict[str, dict[str, str | None]] | None = None
        if prediction.votes is not None:
            got_ids = set(prediction.votes)
            if got_ids != expected_ids:
                details: list[str] = []
                missing = sorted(expected_ids - got_ids)
                extra = sorted(got_ids - expected_ids)
                if missing:
                    details.append("缺 " + "、".join(missing))
                if extra:
                    details.append("多 " + "、".join(extra))
                raise ScoreError(
                    f"{plan.path} 第 {task.line_index + 1} 行："
                    f"預測器回傳的投票鍵不符（{'；'.join(details)}）"
                )
            votes_payload = {
                qid: {"label": vote.label, "prob": vote.prob}
                for qid, vote in prediction.votes.items()
            }

        jury_votes = prediction.jury_votes
        if jury_votes is not None and set(jury_votes) != expected_ids:
            raise ScoreError(
                f"{plan.path} 第 {task.line_index + 1} 行："
                "預測器回傳的 juryVotes 鍵不符"
            )

        record = plan.records[task.line_index]
        assert record is not None  # _collect_tasks 已剔除空白行
        # v1 的舊欄位（label／prob）一併移除，避免 extra="forbid" 擋下新檔。
        record.pop("label", None)
        record.pop("prob", None)
        if prediction.votes is None:
            # 整則失敗（全員失敗／平手無法聚合）：回到「未評分」狀態。
            # 帶著 judge／juryVotes 的 votes=null 記錄不是合法的 v1.2 形狀，
            # 也不該被 build 當成已評分。重跑（或 --force）會自動重試。
            record["votes"] = None
            record["judge"] = None
            record.pop("juryVotes", None)
            changed.setdefault(task.file_index, set()).add(task.line_index)
            continue
        record["votes"] = votes_payload
        record["judge"] = judge
        if jury_votes is None:
            record.pop("juryVotes", None)
        else:
            record["juryVotes"] = jury_votes
        changed.setdefault(task.file_index, set()).add(task.line_index)

    scored = 0
    for file_index, line_indices in sorted(changed.items()):
        plan = plans[file_index]
        output: list[str] = []
        for line_index, raw in enumerate(plan.lines):
            if line_index in line_indices:
                record = plan.records[line_index]
                output.append(json.dumps(record, ensure_ascii=False))
            else:
                output.append(raw)
        _atomic_write_jsonl(plan.path, output)
        scored += len(line_indices)

    print(f"arena score：已評分 {scored} 則（judge={judge}）。")
    report = getattr(predictor, "failure_report", None)
    if callable(report):
        message = report()
        if message:
            print(message, file=sys.stderr)
    return EXIT_OK


def score_paths(
    paths: Sequence[Path],
    predictor: Predictor,
    *,
    force: bool = False,
) -> int:
    """對指定的 evidence 檔評分；回傳結束碼。可注入 predictor 以便測試。"""
    plans = [_load_file(path) for path in paths]
    tasks = _collect_tasks(plans, force)
    if not tasks:
        print("arena score：所有貼文都已評分，無需處理。")
        return EXIT_OK
    return _apply(plans, tasks, predictor)


def _split_env_paths(raw: str) -> list[str]:
    """把 ``ARENA_EVIDENCE_FILES`` 拆成路徑清單（以 ``os.pathsep`` 分隔）。"""
    return [part.strip() for part in raw.split(os.pathsep) if part.strip()]


def resolve_paths(args: argparse.Namespace) -> list[Path]:
    """決定要處理的 evidence 檔：命令列參數 → 環境變數 → 預設 glob。"""
    files = getattr(args, "files", None) or getattr(args, "paths", None)
    if files:
        return [Path(item) for item in files]

    env_files = os.environ.get("ARENA_EVIDENCE_FILES", "").strip()
    if env_files:
        return [Path(item) for item in _split_env_paths(env_files)]

    return sorted(Path().glob(DEFAULT_EVIDENCE_GLOB))


def _env_flag(name: str) -> bool:
    """把環境變數解析為布林旗標（1/true/yes/on）。"""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """把 score 的參數掛上 argparse 子解析器（cli.py 會自動呼叫）。"""
    parser.add_argument(
        "files",
        metavar="PATH",
        nargs="*",
        help="要評分的 evidence jsonl（預設 data/evidence/*.jsonl）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="重評所有行，包含已有 votes 的行（預設跳過）",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="改走 OpenRouter batch API（半價但非同步，批次要等數分鐘到數小時；"
        "預設為同步呼叫）",
    )


def run(args: argparse.Namespace, predictor: Predictor | None = None) -> int:
    """`arena score` 的進入點。"""
    try:
        paths = resolve_paths(args)
        if not paths:
            print(
                "arena score：找不到 evidence 檔"
                f"（預設 {DEFAULT_EVIDENCE_GLOB}，或以 ARENA_EVIDENCE_FILES 指定）。",
                file=sys.stderr,
            )
            return EXIT_ERROR

        missing = [path for path in paths if not path.exists()]
        if missing:
            for path in missing:
                print(f"arena score：找不到檔案 {path}", file=sys.stderr)
            return EXIT_ERROR

        force = bool(getattr(args, "force", False)) or _env_flag("ARENA_SCORE_FORCE")

        # 先掃描：若沒有任何未評分的行，就不必付呼叫評審的成本（已評分檔可即時結束）。
        plans = [_load_file(path) for path in paths]
        tasks = _collect_tasks(plans, force)
        if not tasks:
            print("arena score：所有貼文都已評分，無需處理。")
            return EXIT_OK

        if predictor is None:
            # 延後匯入：arena.jury 依賴本模組的 QUESTION／Vote／Prediction。
            from arena.jury import build_jury_predictor

            use_batch = bool(getattr(args, "batch", False)) and not _env_flag(
                "ARENA_SCORE_NO_BATCH"
            )
            predictor = build_jury_predictor(use_batch=use_batch)

        return _apply(plans, tasks, predictor)
    except ScoreError as exc:
        print(f"arena score：{exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("arena score：已取消。", file=sys.stderr)
        return EXIT_ERROR


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_EVIDENCE_GLOB",
    "EXIT_ERROR",
    "EXIT_OK",
    "JUDGE",
    "LayaPredictor",
    "MODEL_ID",
    "Prediction",
    "Predictor",
    "QUESTION",
    "QUESTION_ID",
    "REVISION",
    "ScoreError",
    "Vote",
    "add_arguments",
    "build_state",
    "resolve_paths",
    "run",
    "score_paths",
]