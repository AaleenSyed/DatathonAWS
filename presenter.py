"""Presenter: writes the final answer with Claude Sonnet 5 on Amazon Bedrock (Converse API), using only the
run trace. Prompt: prompts/presenter_system.txt.
"""
import json
import os
from pathlib import Path

import boto3
from botocore.config import Config

PROMPTS = Path(__file__).resolve().parent / "prompts"
PRESENTER_MODEL = os.getenv("PRESENTER_MODEL", "global.anthropic.claude-sonnet-5")
MAX_TOKENS = 6000  # Sonnet 5 reasons first; too small -> empty text (CLAUDE.md)
_client = None


def _bedrock():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name="us-east-1",
                               config=Config(retries={"max_attempts": 5, "mode": "adaptive"}))
    return _client


def build_input(persona: dict, question: str, history: list, trace, plan: dict, notes: list, feedback: str | None):
    steps = [{"step": s["step"], "actor": s["actor"], "action": s["action"], "input": s["input"],
              "output": s["output"]} for s in trace.steps if s["actor"].startswith("worker:")]
    payload = {"persona": persona, "question": question, "analysis_date": trace.meta["analysis_date"],
               "earlier_turns": history[-3:], "boss_plan": plan, "reviewer_notes": notes, "trace_steps": steps}
    text = "Write the answer from this run trace (JSON):\n" + json.dumps(payload, default=str)
    if feedback:
        text += f"\n\nYOUR PREVIOUS DRAFT WAS REJECTED BY THE REVIEWER: {feedback}\nRewrite it and fix exactly that."
    return text


def present(persona: dict, question: str, history: list, trace, plan: dict, notes: list,
            feedback: str | None = None) -> str:
    system = (PROMPTS / "presenter_system.txt").read_text(encoding="utf-8").replace("{{PERSONA_NAME}}", persona["name"])
    r = _bedrock().converse(
        modelId=PRESENTER_MODEL,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": build_input(persona, question, history, trace, plan,
                                                                     notes, feedback)}]}],
        inferenceConfig={"maxTokens": MAX_TOKENS},
    )
    blocks = r["output"]["message"]["content"]
    return "".join(b["text"] for b in blocks if "text" in b).strip()
