"""Runs one chat turn for the server: the real pipeline (Bedrock) or the scripted demo agent.

The pipeline keeps the active trace in a process-wide context (agent_tools.CONTEXT), so runs are serialized
with RUN_LOCK: one run at a time; others wait (the server reports them as "queued").
"""
import inspect
import threading

import pipeline
from server import demo_agent

RUN_LOCK = threading.Lock()


def stage_for(step: dict) -> str | None:
    """GenerationStage after a trace step (contracts/openapi.yaml), or None to keep the current one."""
    actor, action = step["actor"], step["action"]
    out = step.get("output") if isinstance(step.get("output"), dict) else {}
    if actor == "user":
        return "planning"
    if actor.startswith("worker:"):
        return "analyzing"
    if actor == "boss":
        return "reviewing"
    if actor == "reviewer" and action == "review_work":
        return "writing" if out.get("verdict") == "pass" else "planning"
    if actor == "presenter":
        return "checking"
    if actor == "reviewer" and action == "check_answer" and out.get("verdict") == "fail":
        return "writing"
    if actor == "pipeline":
        return "done"
    return None


def warm_up():
    """Precompute every persona's sector ranking and the market context (agent_tools cache), holding RUN_LOCK
    because the tools share one process-wide context. Never raises."""
    import agent_tools
    try:
        with RUN_LOCK:
            agent_tools.warm_up(as_of=pipeline.ANALYSIS_DATE)
    except Exception:
        pass


def accepts_delta(fn) -> bool:
    """True when a runner takes an on_delta keyword (test runners may not)."""
    try:
        return "on_delta" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def run_turn(persona: str, question: str, history: list[dict], lang: str, on_step=None, mode: str = "bedrock",
             session_id: str | None = None, runs_dir=None, on_delta=None) -> dict:
    """One question through boss -> workers -> reviewer -> presenter. Blocking; call it from a thread."""
    with RUN_LOCK:
        boss = presenter = None
        if mode == "demo":
            boss, presenter = demo_agent.make(persona, question, lang)
        session = pipeline.ChatSession(persona, boss=boss, presenter=presenter, history=history, lang=lang,
                                       on_step=on_step, session_id=session_id, runs_dir=runs_dir, on_delta=on_delta)
        return session.ask(question)
