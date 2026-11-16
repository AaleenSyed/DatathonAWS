"""Runs one chat turn for the server: the real pipeline (Bedrock) or the scripted demo agent.

The pipeline keeps the active trace in a process-wide context (agent_tools.CONTEXT), so runs are serialized
with RUN_LOCK: one analysis at a time; others wait (the server reports them as "queued"). The guard, the
intent router and the short replies (LLM-written or fixed) run outside the lock.
"""
import functools
import inspect
import threading

import pipeline
import router
from server import demo_agent

RUN_LOCK = threading.Lock()


def stage_for(step: dict) -> str | None:
    """GenerationStage after a trace step (contracts/openapi.yaml), or None to keep the current one."""
    actor, action = step["actor"], step["action"]
    out = step.get("output") if isinstance(step.get("output"), dict) else {}
    if actor == "user":
        return None  # sent before the run lock: the initial stage (queued / planning) stays
    if actor == "router":
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
    try:
        if router.llm_enabled():
            router._model()
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
    boss = presenter = route = None
    if mode == "demo":
        boss, presenter = demo_agent.make(persona, question, lang)
        route = functools.partial(router.route, llm=False)  # demo: rules only, unclear -> scripted pipeline
    session = pipeline.ChatSession(persona, boss=boss, presenter=presenter, history=history, lang=lang,
                                   on_step=on_step, session_id=session_id, runs_dir=runs_dir, on_delta=on_delta,
                                   route=route, lock=RUN_LOCK)
    return session.ask(question)  # guard + router + short replies run before RUN_LOCK; the analysis holds it
