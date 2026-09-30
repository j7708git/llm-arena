#!/usr/bin/env python3
"""Gold 標註的真實 LLM 逐則標註器（2026-09-30，PM 裁定重做）。

背景：第一輪的「四家模型標註」被發現部分出自 regex 腳本或 session 手寫判斷表
（``annotate.py``／``annotate_v2.py``／``build_annotations_qwen.py``），出身不可驗證。
本腳本以 OpenRouter API **逐則、溫度 0、response_format=json_object** 呼叫指定模型，
依 ``docs/annotation-guide.md`` v1.2（R1 主體原則＋R2 轉述型評價）產生標註；
每列 ``annotator`` 欄即 ``--model`` 傳入的實際模型 id，出身可由本檔＋API 帳單重現。

用法（四家各跑一次）::

    export OPENROUTER_API_KEY=sk-or-...
    python tools/annotate_gold.py --model qwen/qwen3.8-flash \
        --annotator qwen3.8-flash --out data/calibration/real/annotations-qwen3.8-flash.jsonl

可續跑：輸出檔已有的 hash 會跳過。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

DEFAULT_WORKSHEET = Path("data/calibration/annotation-worksheet.jsonl")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
_RETRYABLE = {408, 425, 429, 500, 502, 503, 504}


def post_chat(
    api_key: str, model: str, messages: list[dict[str, str]], *, max_tokens: int
) -> str:
    """單次 chat/completions（溫度 0、JSON 模式）；429/5xx 指數退避後丟例外。"""
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    last: str = ""
    for attempt in range(4):
        try:
            response = httpx.post(
                API_URL, headers=headers, json=body, timeout=120.0
            )
        except httpx.HTTPError as exc:
            last = f"網路錯誤：{exc}"
        else:
            if response.status_code in _RETRYABLE:
                last = f"HTTP {response.status_code}"
            elif response.status_code >= 400:
                raise RuntimeError(
                    f"HTTP {response.status_code}：{response.text[:200]}"
                )
            else:
                content = (
                    response.json()["choices"][0]["message"].get("content") or ""
                ).strip()
                if not content:
                    raise RuntimeError("回應內容為空")
                return content
        if attempt < 3:
            time.sleep(3 * 2**attempt)
    raise RuntimeError(f"重試 4 次後仍失敗：{last}")

FACETS = ("quality", "speed", "tokenEfficiency", "tokenUsage", "priceValue")
OVERALL_LABELS = {"positive", "negative", "neutral"}
FACET_LABELS = {"positive", "negative", "not-discussed"}

SYSTEM_PROMPT = """You are a strict, impartial annotation judge building a gold-standard \
dataset about community sentiment toward AI models. Read the social-media post and label \
the author's attitude. You must answer in JSON and nothing else.

Label exactly these six fields:
- "overall": the author's overall attitude toward the AI model discussed in this post. \
One of: positive | negative | neutral.
- "quality": attitude toward the model's capability and output quality (correctness, \
intelligence, reliability). positive | negative | not-discussed.
- "speed": attitude toward response speed, latency, or throughput. \
positive | negative | not-discussed.
- "tokenEfficiency": attitude toward how concisely the model answers and how efficiently \
it uses context and tokens. positive | negative | not-discussed.
- "tokenUsage": attitude toward how many tokens (or how much of a usage quota) the model \
consumes to complete tasks. positive | negative | not-discussed.
- "priceValue": attitude toward the model's price and value for money (API pricing, \
subscription cost, free-tier value). positive | negative | not-discussed.
- "notes": optional short flag from: off_target | mixed | truncated | null.

Hard rules:
1. Overall measures the AUTHOR's own stance; the five facets measure the sentiment that \
leaks out when a facet is mentioned, regardless of who said it (paraphrased ads, official \
announcements, third-party benchmark claims still color the facet).
2. Subject rule: if the post's main praised/criticized subject is NOT the modelId given in \
the user message (e.g. it discusses a different or unlisted model, a company, a person, \
or pure hype), then overall=neutral, ALL five facets=not-discussed, notes="off_target".
3. Facets: use not-discussed when the facet is not discussed or mentioned without any \
stance. A bare factual comparison ("A costs $12/M, B costs $8/M") without a stated \
preference is not-discussed for priceValue. Directional claims count: "30% faster" -> \
speed=positive; "half price" -> priceValue=positive; "ranked second, beats X" -> \
quality=positive (and quality=negative if the losing side is the modelId).
4. Sarcasm is labeled by meaning, not literal words ("Oh great, it hallucinated again" -> \
negative). Negations by intent: "can't recommend it enough" -> positive; "not bad at all" \
-> positive; "not a fan" -> negative; "hardly the improvement" -> negative.
5. Mixed tone: pick the dominant tone; only when truly undecidable use overall=neutral \
and notes="mixed". Facets are judged independently regardless of mixed overall.
6. Marketing/announcement copy with no author evaluation -> overall=neutral; directional \
claims inside it still color the facets (rule 3).
7. Answer with exactly one valid JSON object; every field present; no extra keys."""

USER_TMPL = """modelId: {model_id}
post:
{text}

Return the JSON object now."""


def _extract_json(content: str) -> str:
    """有些模型會用 ```json 圍欄或前後加字——抽出第一個 { 到最後一個 }。"""
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end <= start:
        return content
    return content[start : end + 1]


def _validate(payload: dict) -> dict | None:
    """標籤齊全且合法回正規化 dict；否則回 None。"""
    expected = {"overall", "notes", *FACETS}
    if set(payload) != expected:
        return None
    if payload["overall"] not in OVERALL_LABELS:
        return None
    if payload["notes"] is not None and not isinstance(payload["notes"], str):
        return None
    out = {"gold_overall": payload["overall"]}
    for facet in FACETS:
        value = payload[facet]
        if value not in FACET_LABELS:
            return None
        out[f"gold_{facet}"] = value
    out["notes"] = payload["notes"]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="OpenRouter model id")
    parser.add_argument("--annotator", required=True, help="寫進 annotator 欄的短名")
    parser.add_argument("--out", required=True, help="輸出 JSONL 路徑")
    parser.add_argument("--worksheet", type=Path, default=DEFAULT_WORKSHEET)
    parser.add_argument("--start", type=int, default=0, help="從第 N 列開始（0-based）")
    parser.add_argument(
        "--end", type=int, default=None, help="做到第 N 列之前（並行分割用）"
    )
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.worksheet.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["hash"])

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print("缺少 OPENROUTER_API_KEY", file=sys.stderr)
        return 1

    failures = 0
    end = args.end if args.end is not None else len(rows)
    for index in range(args.start, min(end, len(rows))):
        row = rows[index]
        if row["hash"] in done:
            continue
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_TMPL.format(
                    model_id=row["modelId"], text=row["text"]
                ),
            },
        ]
        payload = None
        for attempt in range(3):
            try:
                # max_tokens 給足：推理模型會先燒 reasoning tokens 再吐 JSON，
                # 上限太小會得到空 content（實測 300 不夠；nemotron 需要 3000）。
                content = post_chat(
                    api_key, args.model, messages, max_tokens=3000
                )
                payload = _validate(json.loads(_extract_json(content)))
            except Exception as exc:  # noqa: BLE001 — 逐則容錯，失敗記錄後續跑
                if attempt == 2:
                    print(
                        f"[{index + 1}/{len(rows)}] {row['hash'][:12]} 失敗：{exc}",
                        file=sys.stderr,
                    )
                time.sleep(2 * (attempt + 1))
                continue
            break
        if payload is None:
            failures += 1
            continue
        record = {
            "hash": row["hash"],
            **payload,
            "annotator": args.annotator,
            "annotatedAt": time.strftime("%Y-%m-%d"),
        }
        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if (index + 1) % 25 == 0:
            print(f"[{index + 1}/{len(rows)}] 完成", flush=True)

    print(
        f"{args.annotator}: 輸出 {out_path}（本輪新標 {len(rows) - len(done) - failures}，"
        f"失敗 {failures}）"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
