"""Presenter: writes the final answer on Amazon Bedrock (Converse stream API), using only the run trace.
Prompt: prompts/presenter_system.txt. Default model: Claude Sonnet 4.6 (PRESENTER_MODEL to override).

The text is streamed: `on_delta(chunk)` is called for every piece of text as it arrives, so the UI can show the
answer while it is being written. The presenter reads only the trace steps the plan uses (see relevant_steps);
the full trace stays in the run trace for the explainer, the UI and check_answer.
"""
import json
import os
import time
from pathlib import Path

import boto3
from botocore.config import Config

from texts import lang_or_default, text as ui_text

PROMPTS = Path(__file__).resolve().parent / "prompts"
PRESENTER_MODEL = os.getenv("PRESENTER_MODEL", "global.anthropic.claude-sonnet-4-6")
MAX_TOKENS = int(os.getenv("PRESENTER_MAX_TOKENS", "1500"))
ALWAYS = {"list_sectors", "cycle_phase", "fear_hope", "rank_sectors", "compare_metrics"}
_client = None


def _bedrock():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name="us-east-1",
                               config=Config(retries={"max_attempts": 5, "mode": "adaptive"}))
    return _client


def _norm(s) -> str:
    return str(s or "").strip().lower()


def _target(step) -> str | None:
    i = step.get("input") or {}
    return i.get("ticker") or i.get("sector") or i.get("target") or i.get("tickers_or_sector") or i.get("sector_or_ticker")


def relevant_steps(trace, plan: dict) -> list[dict]:
    """Worker steps the answer can use: market context, sector list, ranking, every step about a requested or
    recommended target, and suitability steps that flag ESG-review names. Other groups ranked by
    rank_sectors_for_persona stay in the trace but are not sent (fewer tokens, faster answer)."""
    plan = plan or {}
    names = {_norm(t) for t in list(plan.get("requested_targets") or []) + list(plan.get("recommended_sectors") or [])}
    out = []
    for s in trace.steps:
        if not s["actor"].startswith("worker:"):
            continue
        o = s["output"] if isinstance(s["output"], dict) else {}
        esg = s["action"] == "check_suitability" and o.get("status") == "ok" and any(
            c["rule"] == "esg_review" and c["status"] == "flag" for c in o["data"]["checks"])
        if s["action"] in ALWAYS or _norm(_target(s)) in names or esg or not names:
            out.append(s)
    return out


def build_input(persona: dict, question: str, history: list, trace, plan: dict, notes: list, feedback: str | None):
    steps = [{"step": s["step"], "actor": s["actor"], "action": s["action"], "input": s["input"],
              "output": s["output"]} for s in relevant_steps(trace, plan)]
    payload = {"persona": persona, "question": question, "analysis_date": trace.meta["analysis_date"],
               "earlier_turns": history[-3:], "boss_plan": plan, "reviewer_notes": notes, "trace_steps": steps}
    text = "Write the answer from this run trace (JSON):\n" + json.dumps(payload, default=str)
    if feedback:
        text += f"\n\nYOUR PREVIOUS DRAFT WAS REJECTED BY THE REVIEWER: {feedback}\nRewrite it and fix exactly that."
    return text


def system_prompt(persona: dict, lang: str = "en") -> str:
    """presenter_system.txt with the language rules (prompts/lang_<code>.txt) and the closing disclaimer."""
    lang = lang_or_default(lang)
    rules = (PROMPTS / f"lang_{lang}.txt").read_text(encoding="utf-8").replace(
        "{{DISCLAIMER}}", ui_text(lang, "disclaimer", name=persona["name"]))
    return ((PROMPTS / "presenter_system.txt").read_text(encoding="utf-8")
            .replace("{{PERSONA_NAME}}", persona["name"]).replace("{{LANGUAGE_RULES}}", rules))


def present(persona: dict, question: str, history: list, trace, plan: dict, notes: list,
            feedback: str | None = None, lang: str = "en", on_delta=None) -> str:
    """Write the answer. on_delta(chunk) gets every text chunk as it is generated (optional)."""
    t0 = time.perf_counter()
    r = _bedrock().converse_stream(
        modelId=PRESENTER_MODEL,
        system=[{"text": system_prompt(persona, lang)}],
        messages=[{"role": "user", "content": [{"text": build_input(persona, question, history, trace, plan,
                                                                     notes, feedback)}]}],
        inferenceConfig={"maxTokens": MAX_TOKENS},
    )
    parts, usage, stop, first_ms = [], {}, None, None
    for event in r["stream"]:
        if "contentBlockDelta" in event:
            chunk = event["contentBlockDelta"]["delta"].get("text")
            if chunk:
                if first_ms is None:
                    first_ms = (time.perf_counter() - t0) * 1000
                    if trace.meta.get("first_text_ms") is None:
                        trace.meta["first_text_ms"] = trace.elapsed_ms()
                parts.append(chunk)
                if on_delta:
                    try:
                        on_delta(chunk)
                    except Exception:  # a broken UI listener must not break the answer
                        pass
        elif "messageStop" in event:
            stop = event["messageStop"].get("stopReason")
        elif "metadata" in event:
            usage = event["metadata"].get("usage") or {}
    trace.record_llm("presenter", "answer", (time.perf_counter() - t0) * 1000, model=PRESENTER_MODEL,
                     first_text_ms=None if first_ms is None else round(first_ms), stop=stop)
    trace.record_usage("presenter", "answer", {k: usage.get(k, 0) for k in ("inputTokens", "outputTokens")})
    return "".join(parts).strip()
