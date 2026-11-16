"""Chat pipeline: ROUTER (rules, then Haiku) -> BOSS (Strands agent on Bedrock) -> worker tools
-> REVIEWER (max 2 retries) -> PRESENTER (streamed) -> answer check (max 1 retry) -> run trace saved locally + S3.

ChatSession keeps the boss agent (and so the conversation) across turns for one persona.
boss / presenter are injectable for tests.
"""
import contextlib
import functools
import json
import os
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

import agent_tools
import guardrail
import reviewer
import router
from personas import PERSONAS
from presenter import present as bedrock_present
from run_trace import RunTrace
from texts import lang_or_default, text, text_variant

load_dotenv(Path(__file__).resolve().parent / ".env")
PROMPTS = Path(__file__).resolve().parent / "prompts"
ANALYSIS_DATE = "2026-11-12"  # last day of the starter dataset
# Fastest model that got every benchmark plan right (scripts/benchmark.py, reports/bench_*.json)
BOSS_MODEL = os.getenv("BOSS_MODEL", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
MAX_REVIEW_RETRIES = 2
MAX_ANSWER_RETRIES = 1
BOSS_LIMITS = {"turns": 4}  # 2 expected: all tools in parallel, then the plan
BOSS_MAX_TOKENS = 2000
HISTORY_TURNS = 3  # earlier turns given to the boss and the presenter
DISCLAIMER = text("en", "disclaimer", name="{name}")


class BossPlan(BaseModel):
    """Plan returned by the boss after running the tools."""
    requested_targets: list[str] = Field(description="tickers / sector groups the user asked about")
    recommended_sectors: list[str] = Field(description="1-2 exact sector group names from list_sectors")
    conflicts_found: list[str] = Field(description="conflicts between the request and the persona, with numbers")
    reasoning_notes: str = Field(description="at most 2 short sentences: assumptions, gaps, why these sectors")


def history_messages(history: list[dict]) -> list[dict]:
    """Earlier turns [{"question", "answer"}] as Bedrock/Strands chat messages (user, assistant, ...)."""
    out = []
    for turn in history[-HISTORY_TURNS:]:
        if turn.get("question") and turn.get("answer"):
            out += [{"role": "user", "content": [{"text": turn["question"]}]},
                    {"role": "assistant", "content": [{"text": turn["answer"]}]}]
    return out


def _ms_since(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000


def boss_timer():
    """Strands hook provider that records every boss model call in the active trace (agent_tools.CONTEXT):
    kind "plan" when the call returns the BossPlan structured output (or ends the turn), else "tool_turn"."""
    from strands.hooks import AfterModelCallEvent, BeforeModelCallEvent, HookProvider

    class BossTimer(HookProvider):
        def __init__(self):
            self.t0 = None

        def register_hooks(self, registry, **kwargs):
            registry.add_callback(BeforeModelCallEvent, self.before)
            registry.add_callback(AfterModelCallEvent, self.after)

        def before(self, event):
            self.t0 = time.perf_counter()

        def after(self, event):
            trace = agent_tools.CONTEXT.get("trace")
            if trace is None or self.t0 is None:
                return
            r = event.stop_response
            uses = [c["toolUse"]["name"] for c in (r.message.get("content") or []) if "toolUse" in c] if r else []
            plan = BossPlan.__name__ in uses or (r is not None and not uses)
            trace.record_llm("boss", "plan" if plan else "tool_turn", _ms_since(self.t0),
                             tools=len([u for u in uses if u != BossPlan.__name__]),
                             stop=str(r.stop_reason) if r else f"error: {event.exception}")
            self.t0 = None

    return BossTimer()


def _usage(result) -> dict:
    u = getattr(getattr(result, "metrics", None), "accumulated_usage", None) or {}
    return {k: int(u.get(k) or 0) for k in ("inputTokens", "outputTokens")}


def make_boss(persona_key: str, as_of: str, history: list[dict] | None = None):
    """Strands agent with the worker tools. Returns a callable(prompt) -> plan dict (or {} if none).

    history: earlier turns of this conversation branch, so a new session can continue a conversation
    (the web server rebuilds the session for every message, which makes edit / regenerate branches work)."""
    from botocore.config import Config
    from strands import Agent
    from strands.models import BedrockModel

    persona = PERSONAS[persona_key]
    system = ((PROMPTS / "boss_system.txt").read_text(encoding="utf-8")
              .replace("{{PERSONA}}", json.dumps(persona, indent=1))
              .replace("{{AS_OF}}", as_of).replace("{{WINDOW_START}}", agent_tools.WINDOW_START)
              .replace("{{GROUPS}}", agent_tools.groups_text()))
    model = BedrockModel(model_id=BOSS_MODEL, region_name="us-east-1", max_tokens=BOSS_MAX_TOKENS,
                         boto_client_config=Config(retries={"max_attempts": 5, "mode": "adaptive"}))
    agent = Agent(model=model, tools=agent_tools.TOOLS, system_prompt=system, callback_handler=None,
                  messages=history_messages(history or []), hooks=[boss_timer()])
    seen = {"inputTokens": 0, "outputTokens": 0}  # metrics accumulate over the agent's life

    def run(prompt: str) -> dict:
        r = agent(prompt, structured_output_model=BossPlan, limits=BOSS_LIMITS)
        total = _usage(r)
        trace = agent_tools.CONTEXT.get("trace")
        if trace is not None:
            trace.record_usage("boss", "round", {k: total[k] - seen[k] for k in total})
        seen.update(total)
        return r.structured_output.model_dump() if r.structured_output else {}
    return run


class ChatSession:
    def __init__(self, persona: str, boss=None, presenter=None, as_of: str = ANALYSIS_DATE, runs_dir=None,
                 history: list[dict] | None = None, lang: str = "en", on_step=None, session_id: str | None = None,
                 on_delta=None, guard=None, route=None, lock=None):
        """history: earlier turns [{"question", "answer"}] to continue a conversation.
        lang: answer language ("en" or "fr"). on_step: callable(step) for every trace step (live UI).
        on_delta: callable(text, reset) for the answer text as it is streamed (reset=True: discard the text
        streamed so far, the reviewer asked for a rewrite). Only the Bedrock presenter streams.
        guard: callable(text, source) -> {"action", ...} applying the Bedrock Guardrail (default guardrail.check,
        skipped when GUARDRAIL_ID is unset or AGENT_MODE=demo). Injectable for tests.
        route: callable(question, history) -> router.route()-style dict (default router.route).
        lock: context manager held around the analysis only (server passes RUN_LOCK); guard, router and short
        replies run outside it."""
        key = str(persona).strip().lower()
        if key not in PERSONAS:
            raise ValueError(f"unknown persona '{persona}'; choose one of {sorted(PERSONAS)}")
        self.persona_key, self.persona, self.as_of = key, PERSONAS[key], as_of
        self.lang = lang_or_default(lang)
        turns = [dict(h) for h in (history or [])]
        # short-reply turns ({"intent": "smalltalk" | "about" | "off_topic"}) never reach the boss / presenter
        self.history: list[dict] = [h for h in turns if h.get("intent", "analysis") == "analysis"]
        self.chat_turns = len(turns) - len(self.history)  # still counted in the turn number (rotates fixed replies)
        self.boss = boss  # None: built on the first analysis turn (a greeting never builds it)
        self.route = route or router.route
        self.lock = lock or contextlib.nullcontext()
        self.on_delta = on_delta
        self.present = presenter or functools.partial(bedrock_present, lang=self.lang, on_delta=self._delta)
        self._streamed = False
        self.runs_dir = runs_dir
        self.on_step = on_step
        self.session_id = session_id or uuid.uuid4().hex[:8]
        self.guard = guard or guardrail.check

    def _delta(self, chunk: str):
        self._streamed = True
        if self.on_delta:
            self.on_delta(chunk, False)

    def _call_boss(self, trace, prompt, label):
        t0 = time.perf_counter()
        try:
            plan = self.boss(prompt) or {}
        except Exception as e:
            plan = {}
            trace.add("boss", f"{label}_error", {"prompt": guardrail.redact_pii(prompt[:500])},
                      {"status": "error", "error": str(e)})
        trace.add("boss", label, {"prompt": guardrail.redact_pii(prompt[:500])}, plan, duration_ms=_ms_since(t0))
        return plan

    def _review_work(self, trace, plan, question, attempt):
        t0 = time.perf_counter()
        verdict = reviewer.review_work(trace, plan, self.persona_key, question, self.as_of)
        trace.add("reviewer", "review_work", {"attempt": attempt}, verdict, duration_ms=_ms_since(t0))
        return verdict

    def _guard(self, trace, content: str, source: str) -> bool:
        """Apply the Bedrock Guardrail to the question (INPUT) or the final answer (OUTPUT). True = blocked.
        Logged in the trace only when the guardrail is configured; the logged text is PII-redacted and the
        matched content is never stored. An API error fails open (the run continues) and is logged."""
        t0 = time.perf_counter()
        try:
            r = self.guard(content, source) or {}
        except Exception as e:
            r = {"action": "ERROR", "assessments": [], "error": str(e)[:300]}
        if r.get("action") == "SKIPPED":
            return False
        blocked = r.get("action") == "GUARDRAIL_INTERVENED"
        status = "blocked" if blocked else "error" if r.get("action") == "ERROR" else "ok"
        trace.add("guardrail", f"{source.lower()}_{'blocked' if blocked else 'checked'}",
                  {"source": source, "text": guardrail.redact_pii(content)[:500]},
                  {"status": status, **{k: v for k, v in r.items() if k != "source"}}, duration_ms=_ms_since(t0))
        return blocked

    def _blocked(self, trace, source: str) -> str:
        answer = text(self.lang, "guardrail_block", name=self.persona["name"])
        trace.add("pipeline", "final_answer", None, {"answer": answer, "work_verdict": "blocked",
                                                     "answer_verdict": "blocked", "blocked_by": source})
        return answer

    def _route(self, trace, question, safe_question):
        """Classify the message. Returns (intent, trace.add args for the router/route step). Never raises."""
        t0 = time.perf_counter()
        try:
            r = dict(self.route(question, self.history) or {})
        except Exception as e:
            r = {"reason": f"router error: {str(e)[:200]}"}
        if r.get("intent") not in router.INTENTS:
            r.update(intent="analysis", method="default")
        if r.get("llm_ms") is not None:
            trace.record_llm("router", "classify", r["llm_ms"], stop=r.get("stop"))
        trace.record_usage("router", "classify", r.get("usage"))
        out = {"intent": r["intent"], "method": r.get("method") or "default",
               "reason": guardrail.redact_pii(str(r.get("reason") or ""))[:200], "model": r.get("model")}
        return r["intent"], ("router", "route", {"question": safe_question[:500]}, out, _ms_since(t0))

    def _short_reply(self, trace, question, safe_question, intent, turn) -> dict:
        """Fixed text (texts.py) for smalltalk / about / off_topic: no boss, no presenter, no tool context."""
        answer = text_variant(self.lang, router.reply_key(intent, question), turn, name=self.persona["name"])
        skipped = {"verdict": "skipped", "reasons": [f"{intent}: fixed reply, no analysis"]}
        trace.add("pipeline", "final_answer", None, {"answer": answer, "intent": intent, "work_verdict": "skipped",
                                                     "answer_verdict": "skipped"})
        return self._finish(trace, safe_question, answer, {}, skipped, skipped, intent=intent)

    def ask(self, question: str) -> dict:
        safe_question = guardrail.redact_pii(question)  # stored in the trace (local + S3); the models get the original
        turn = len(self.history) + self.chat_turns + 1
        trace = RunTrace(self.persona["name"], safe_question, self.as_of, turn, self.session_id,
                         listener=self.on_step, language=self.lang)
        trace.add("user", "question", {"persona": self.persona_key}, {"question": safe_question,
                                                                     "persona_profile": self.persona})
        if self._guard(trace, question, "INPUT"):  # blocked: no router, no boss, no presenter
            blocked = {"verdict": "blocked", "reasons": ["input blocked by the Bedrock Guardrail"]}
            return self._finish(trace, safe_question, self._blocked(trace, "INPUT"), {}, blocked, blocked)
        intent, route_step = self._route(trace, question, safe_question)
        if intent != "analysis":
            trace.add(*route_step)
            return self._short_reply(trace, question, safe_question, intent, turn)
        t_wait = time.perf_counter()
        with self.lock:  # agent_tools.CONTEXT is process-wide: only touched while the lock is held
            trace.meta["queued_ms"] = round((time.perf_counter() - t_wait) * 1000)
            trace.add(*route_step)  # added once the run really starts, so a queued run shows "queued" until then
            if self.boss is None:
                self.boss = make_boss(self.persona_key, self.as_of, self.history)
            agent_tools.CONTEXT.update(trace=trace, persona=self.persona_key, as_of=self.as_of)
            try:
                return self._analyze(trace, question, safe_question)
            finally:
                agent_tools.CONTEXT["trace"] = None

    def _analyze(self, trace, question, safe_question) -> dict:
        plan = self._call_boss(trace, question, "plan")
        verdict = self._review_work(trace, plan, question, 0)
        retries = 0
        while verdict["verdict"] == "fail" and retries < MAX_REVIEW_RETRIES:
            retries += 1
            prompt = "REVIEWER FAIL. Fix these, then return the updated plan:\n- " + "\n- ".join(verdict["reasons"])
            plan = self._call_boss(trace, prompt, f"plan_retry_{retries}") or plan
            verdict = self._review_work(trace, plan, question, retries)
        notes = [] if verdict["verdict"] == "pass" else [
            "INCOMPLETE ANALYSIS after 2 reviewer retries: " + "; ".join(verdict["reasons"])]

        answer, check, feedback = "", {"verdict": "fail", "reasons": ["not written"]}, None
        for attempt in range(MAX_ANSWER_RETRIES + 1):
            if attempt and self._streamed and self.on_delta:
                self.on_delta("", True)  # the rejected draft was already shown: clear it
            self._streamed = False
            t0 = time.perf_counter()
            try:
                answer = self.present(self.persona, question, self.history, trace, plan, notes, feedback)
            except Exception as e:
                answer = ""
                check = {"verdict": "fail", "reasons": [f"presenter error: {e}"]}
                trace.add("presenter", "write_answer", {"attempt": attempt}, check, duration_ms=_ms_since(t0))
                continue
            trace.add("presenter", "write_answer", {"attempt": attempt}, {"answer": guardrail.redact_pii(answer)},
                      duration_ms=_ms_since(t0))
            t0 = time.perf_counter()
            check = reviewer.check_answer(answer, trace, lang=self.lang)
            trace.add("reviewer", "check_answer", {"attempt": attempt}, check, duration_ms=_ms_since(t0))
            if check["verdict"] == "pass":
                break
            feedback = "; ".join(check["reasons"])
        if not answer:
            answer = text(self.lang, "no_answer")
        if check["verdict"] == "fail":
            answer += "\n\n" + text(self.lang, "reviewer_note", reasons="; ".join(check["reasons"]))
        if notes:
            answer = text(self.lang, "incomplete") + "\n\n" + answer
        disclaimer = text(self.lang, "disclaimer", name=self.persona["name"])
        if disclaimer not in answer:
            answer += "\n\n" + disclaimer
        if self._guard(trace, answer, "OUTPUT"):
            if self._streamed and self.on_delta:
                self.on_delta("", True)  # the blocked draft was already streamed: clear it
            check = {"verdict": "blocked", "reasons": ["answer blocked by the Bedrock Guardrail"]}
            return self._finish(trace, safe_question, self._blocked(trace, "OUTPUT"), plan, verdict, check)
        trace.add("pipeline", "final_answer", None, {"answer": answer, "work_verdict": verdict["verdict"],
                                                     "answer_verdict": check["verdict"]})
        return self._finish(trace, question, answer, plan, verdict, check)

    def _finish(self, trace, question, answer, plan, verdict, check, intent="analysis") -> dict:
        """Save the trace and record the turn in the session history (a blocked turn keeps the redacted question)."""
        saved = trace.save(self.runs_dir)
        if intent == "analysis":
            self.history.append({"question": question, "answer": answer})
        else:
            self.chat_turns += 1
        return {"answer": answer, "plan": plan, "work_verdict": verdict, "answer_verdict": check,
                "trace": trace, "saved": saved, "timing": trace.timing(), "intent": intent}
