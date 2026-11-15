"""Chat pipeline: BOSS (Strands agent, Sonnet 5 on Bedrock) -> worker tools -> REVIEWER (max 2 retries)
-> PRESENTER (Sonnet 5) -> answer check (max 2 retries) -> run trace saved locally + S3.

ChatSession keeps the boss agent (and so the conversation) across turns for one persona.
boss / presenter are injectable for tests.
"""
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

load_dotenv(Path(__file__).resolve().parent / ".env")
PROMPTS = Path(__file__).resolve().parent / "prompts"
ANALYSIS_DATE = "2026-11-12"  # last day of the starter dataset
BOSS_MODEL = os.getenv("BOSS_MODEL", "global.anthropic.claude-sonnet-5")
MAX_REVIEW_RETRIES = 2
MAX_ANSWER_RETRIES = 2
BOSS_LIMITS = {"turns": 8}
DISCLAIMER = "_Educational simulation for a fictional persona ({name}). Not personalized financial advice._"


class BossPlan(BaseModel):
    """Plan returned by the boss after running the tools."""
    requested_targets: list[str] = Field(description="tickers / sector groups the user asked about")
    recommended_sectors: list[str] = Field(description="1-2 exact sector group names from list_sectors")
    conflicts_found: list[str] = Field(description="conflicts between the request and the persona, with numbers")
    reasoning_notes: str = Field(description="short notes: assumptions made, gaps, why these sectors")


def make_boss(persona_key: str, as_of: str):
    """Strands agent with the worker tools. Returns a callable(prompt) -> plan dict (or {} if none)."""
    from botocore.config import Config
    from strands import Agent
    from strands.models import BedrockModel

    persona = PERSONAS[persona_key]
    system = ((PROMPTS / "boss_system.txt").read_text(encoding="utf-8")
              .replace("{{PERSONA}}", json.dumps(persona, indent=1))
              .replace("{{AS_OF}}", as_of).replace("{{WINDOW_START}}", agent_tools.WINDOW_START))
    model = BedrockModel(model_id=BOSS_MODEL, region_name="us-east-1", max_tokens=8000,
                         boto_client_config=Config(retries={"max_attempts": 5, "mode": "adaptive"}))
    agent = Agent(model=model, tools=agent_tools.TOOLS, system_prompt=system, callback_handler=None)

    def run(prompt: str) -> dict:
        r = agent(prompt, structured_output_model=BossPlan, limits=BOSS_LIMITS)
        return r.structured_output.model_dump() if r.structured_output else {}
    return run


class ChatSession:
    def __init__(self, persona: str, boss=None, presenter=None, as_of: str = ANALYSIS_DATE, runs_dir=None,
                 semantic=None):
        key = str(persona).strip().lower()
        if key not in PERSONAS:
            raise ValueError(f"unknown persona '{persona}'; choose one of {sorted(PERSONAS)}")
        self.persona_key, self.persona, self.as_of = key, PERSONAS[key], as_of
        self.boss = boss or make_boss(key, as_of)
        self.present = presenter or bedrock_present
        self.runs_dir = runs_dir
        # Haiku 4.5 meaning check after the number check; SEMANTIC_CHECK=0 turns it off (offline tests)
        self.semantic = semantic if semantic is not None else (
            reviewer.semantic_check if os.getenv("SEMANTIC_CHECK", "1") != "0" else None)
        self.session_id = uuid.uuid4().hex[:8]
        self.history: list[dict] = []

    def _call_boss(self, trace, prompt, label):
        try:
            plan = self.boss(prompt) or {}
        except Exception as e:
            plan = {}
            trace.add("boss", f"{label}_error", {"prompt": prompt[:500]}, {"status": "error", "error": str(e)})
        trace.add("boss", label, {"prompt": prompt[:500]}, plan)
        return plan

    def ask(self, question: str) -> dict:
        trace = RunTrace(self.persona["name"], question, self.as_of, len(self.history) + 1, self.session_id)
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
                check = reviewer.check_answer(answer, trace)
                trace.add("reviewer", "check_answer", {"attempt": attempt}, check)
                if check["verdict"] == "pass" and self.semantic:
                    try:
                        sem = self.semantic(answer, trace)
                        trace.add("reviewer", "semantic_check", {"attempt": attempt, "model": reviewer.SEMANTIC_MODEL},
                                  sem)
                        check = {"verdict": sem["verdict"], "reasons": sem["reasons"]}
                    except Exception as e:  # the LLM check must not block an answer whose numbers are verified
                        trace.add("reviewer", "semantic_check", {"attempt": attempt},
                                  {"status": "error", "error": f"semantic check unavailable: {e}"})
                if check["verdict"] == "pass":
                    break
                feedback = "; ".join(check["reasons"])
            if not answer:
                answer = "Sorry, the answer could not be written this time. The analysis is saved in the trace."
            if check["verdict"] == "fail":
                answer += "\n\n> **Reviewer note:** " + "; ".join(check["reasons"])
            if notes:
                answer = "> **Note:** the analysis is incomplete (see trace).\n\n" + answer
            disclaimer = DISCLAIMER.format(name=self.persona["name"])
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
