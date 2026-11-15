"""Chat pipeline: BOSS (Strands agent, Sonnet 5 on Bedrock) -> worker tools -> REVIEWER (max 2 retries)
-> PRESENTER (Sonnet 5) -> answer check (max 2 retries) -> run trace saved locally + S3.

ChatSession keeps the boss agent (and so the conversation) across turns for one persona.
boss / presenter are injectable for tests.
"""
import functools
import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

import agent_tools
import reviewer
from personas import PERSONAS
from presenter import present as bedrock_present
from run_trace import RunTrace
from texts import lang_or_default, text

load_dotenv(Path(__file__).resolve().parent / ".env")
PROMPTS = Path(__file__).resolve().parent / "prompts"
ANALYSIS_DATE = "2026-11-12"  # last day of the starter dataset
BOSS_MODEL = os.getenv("BOSS_MODEL", "global.anthropic.claude-sonnet-5")
MAX_REVIEW_RETRIES = 2
MAX_ANSWER_RETRIES = 2
BOSS_LIMITS = {"turns": 8}
HISTORY_TURNS = 3  # earlier turns given to the boss and the presenter
DISCLAIMER = text("en", "disclaimer", name="{name}")


class BossPlan(BaseModel):
    """Plan returned by the boss after running the tools."""
    requested_targets: list[str] = Field(description="tickers / sector groups the user asked about")
    recommended_sectors: list[str] = Field(description="1-2 exact sector group names from list_sectors")
    conflicts_found: list[str] = Field(description="conflicts between the request and the persona, with numbers")
    reasoning_notes: str = Field(description="short notes: assumptions made, gaps, why these sectors")


def history_messages(history: list[dict]) -> list[dict]:
    """Earlier turns [{"question", "answer"}] as Bedrock/Strands chat messages (user, assistant, ...)."""
    out = []
    for turn in history[-HISTORY_TURNS:]:
        if turn.get("question") and turn.get("answer"):
            out += [{"role": "user", "content": [{"text": turn["question"]}]},
                    {"role": "assistant", "content": [{"text": turn["answer"]}]}]
    return out


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
              .replace("{{AS_OF}}", as_of).replace("{{WINDOW_START}}", agent_tools.WINDOW_START))
    model = BedrockModel(model_id=BOSS_MODEL, region_name="us-east-1", max_tokens=8000,
                         boto_client_config=Config(retries={"max_attempts": 5, "mode": "adaptive"}))
    agent = Agent(model=model, tools=agent_tools.TOOLS, system_prompt=system, callback_handler=None,
                  messages=history_messages(history or []))

    def run(prompt: str) -> dict:
        r = agent(prompt, structured_output_model=BossPlan, limits=BOSS_LIMITS)
        return r.structured_output.model_dump() if r.structured_output else {}
    return run


class ChatSession:
    def __init__(self, persona: str, boss=None, presenter=None, as_of: str = ANALYSIS_DATE, runs_dir=None,
                 history: list[dict] | None = None, lang: str = "en", on_step=None, session_id: str | None = None):
        """history: earlier turns [{"question", "answer"}] to continue a conversation.
        lang: answer language ("en" or "fr"). on_step: callable(step) for every trace step (live UI)."""
        key = str(persona).strip().lower()
        if key not in PERSONAS:
            raise ValueError(f"unknown persona '{persona}'; choose one of {sorted(PERSONAS)}")
        self.persona_key, self.persona, self.as_of = key, PERSONAS[key], as_of
        self.lang = lang_or_default(lang)
        self.history: list[dict] = [dict(h) for h in (history or [])]
        self.boss = boss or make_boss(key, as_of, self.history)
        self.present = presenter or functools.partial(bedrock_present, lang=self.lang)
        self.runs_dir = runs_dir
        self.on_step = on_step
        self.session_id = session_id or uuid.uuid4().hex[:8]

    def _call_boss(self, trace, prompt, label):
        try:
            plan = self.boss(prompt) or {}
        except Exception as e:
            plan = {}
            trace.add("boss", f"{label}_error", {"prompt": prompt[:500]}, {"status": "error", "error": str(e)})
        trace.add("boss", label, {"prompt": prompt[:500]}, plan)
        return plan

    def ask(self, question: str) -> dict:
        trace = RunTrace(self.persona["name"], question, self.as_of, len(self.history) + 1, self.session_id,
                         listener=self.on_step, language=self.lang)
        agent_tools.CONTEXT.update(trace=trace, persona=self.persona_key, as_of=self.as_of)
        try:
            trace.add("user", "question", {"persona": self.persona_key}, {"question": question,
                                                                         "persona_profile": self.persona})
            plan = self._call_boss(trace, question, "plan")
            verdict = reviewer.review_work(trace, plan, self.persona_key, question, self.as_of)
            trace.add("reviewer", "review_work", {"attempt": 0}, verdict)
            retries = 0
            while verdict["verdict"] == "fail" and retries < MAX_REVIEW_RETRIES:
                retries += 1
                prompt = "REVIEWER FAIL. Fix these, then return the updated plan:\n- " + "\n- ".join(verdict["reasons"])
                plan = self._call_boss(trace, prompt, f"plan_retry_{retries}") or plan
                verdict = reviewer.review_work(trace, plan, self.persona_key, question, self.as_of)
                trace.add("reviewer", "review_work", {"attempt": retries}, verdict)
            notes = [] if verdict["verdict"] == "pass" else [
                "INCOMPLETE ANALYSIS after 2 reviewer retries: " + "; ".join(verdict["reasons"])]

            answer, check, feedback = "", {"verdict": "fail", "reasons": ["not written"]}, None
            for attempt in range(MAX_ANSWER_RETRIES + 1):
                try:
                    answer = self.present(self.persona, question, self.history, trace, plan, notes, feedback)
                except Exception as e:
                    answer = ""
                    check = {"verdict": "fail", "reasons": [f"presenter error: {e}"]}
                    trace.add("presenter", "write_answer", {"attempt": attempt}, check)
                    continue
                trace.add("presenter", "write_answer", {"attempt": attempt}, {"answer": answer})
                check = reviewer.check_answer(answer, trace, lang=self.lang)
                trace.add("reviewer", "check_answer", {"attempt": attempt}, check)
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
            trace.add("pipeline", "final_answer", None, {"answer": answer, "work_verdict": verdict["verdict"],
                                                         "answer_verdict": check["verdict"]})
        finally:
            agent_tools.CONTEXT["trace"] = None
        saved = trace.save(self.runs_dir)
        self.history.append({"question": question, "answer": answer})
        return {"answer": answer, "plan": plan, "work_verdict": verdict, "answer_verdict": check,
                "trace": trace, "saved": saved}
