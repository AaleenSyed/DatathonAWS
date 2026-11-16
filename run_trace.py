"""Run trace: every step of one question (who did what, with which input and output). The explainability evidence.

Every step carries `duration_ms` (how long that step took; None when not measured) and `at_ms` (when it
was added, from the start of the run). LLM calls are listed in meta["llm_calls"] and summarized by timing().

Saved as JSON in runs/<run_id>.json and, when DATA_BUCKET is set (and TRACE_S3 != "0"), to
s3://$DATA_BUCKET/runs/<run_id>.json. Saving never raises; a failed upload is recorded in the trace.
"""
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent / "runs"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _summary(output) -> str:
    if isinstance(output, dict):
        if output.get("status") == "error":
            return f"error: {output.get('error')}"
        if "verdict" in output:
            return f"{output['verdict']}: {'; '.join(output.get('reasons', []))[:300]}"
        if output.get("status") == "ok":
            return f"ok; source: {str(output.get('source'))[:120]}; period: {output.get('period')}"
    return str(output)[:300]


class RunTrace:
    def __init__(self, persona: str, question: str, as_of: str, turn: int = 1, session_id: str | None = None,
                 listener=None, language: str = "en"):
        """listener: optional callable(step_dict) called after every step (e.g. to stream it to a UI)."""
        self.run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
        self.meta = {"run_id": self.run_id, "session_id": session_id, "turn": turn, "persona": persona,
                     "question": question, "analysis_date": as_of, "language": language, "started": _now()}
        self.meta["llm_calls"] = []  # {"role", "kind", "ms", "at_ms", ...} per model call
        self.meta["llm_usage"] = []  # token usage per boss round / presenter call
        self.steps: list[dict] = []
        self._t0 = time.perf_counter()
        self._lock = threading.Lock()  # Strands may run tools concurrently; step numbers must stay unique
        self._listener = listener

    def elapsed_ms(self) -> int:
        return round((time.perf_counter() - self._t0) * 1000)

    def add(self, actor: str, action: str, input=None, output=None, duration_ms: float | None = None) -> int:
        """Append a step and return its number (1-based), which answers cite as [fact: step N].
        duration_ms is kept outside input/output, so timings never count as evidence numbers."""
        with self._lock:
            n = len(self.steps) + 1
            step = {"step": n, "actor": actor, "action": action, "input": input, "output": output,
                    "output_summary": _summary(output), "timestamp": _now(),
                    "duration_ms": None if duration_ms is None else round(duration_ms), "at_ms": self.elapsed_ms()}
            self.steps.append(step)
        if self._listener:
            try:
                self._listener(dict(step))
            except Exception:  # a broken listener must never break the analysis
                pass
        return n

    def record_llm(self, role: str, kind: str, ms: float | None, **extra):
        """One model call: role "boss" (kind "tool_turn" or "plan"), "presenter" (kind "answer") or "router" (kind "classify")."""
        with self._lock:
            self.meta["llm_calls"].append({"role": role, "kind": kind, "ms": None if ms is None else round(ms),
                                           "at_ms": self.elapsed_ms(), **extra})

    def record_usage(self, role: str, label: str, usage: dict | None):
        if usage:
            with self._lock:
                self.meta["llm_usage"].append({"role": role, "label": label, **usage})

    def timing(self) -> dict:
        """Where the time went. boss_turns / boss_plan = model time of the boss's tool-calling turns and of its
        final plan; tools = boss wall time not spent in the model (tool execution, overhead)."""
        def dur(pred):
            return sum(s.get("duration_ms") or 0 for s in self.steps if pred(s))
        boss_llm = [c for c in self.meta["llm_calls"] if c["role"] == "boss"]
        boss_ms = dur(lambda s: s["actor"] == "boss")
        llm_boss_ms = sum(c["ms"] or 0 for c in boss_llm)
        usage = {k: sum(u.get(k) or 0 for u in self.meta["llm_usage"]) for k in ("inputTokens", "outputTokens")}
        return {
            "boss_turns_ms": sum(c["ms"] or 0 for c in boss_llm if c["kind"] == "tool_turn"),
            "boss_plan_ms": sum(c["ms"] or 0 for c in boss_llm if c["kind"] == "plan"),
            "tools_ms": max(0, boss_ms - llm_boss_ms) if boss_llm else boss_ms,
            "boss_ms": boss_ms,
            "reviewer_ms": dur(lambda s: s["actor"] == "reviewer"),
            "presenter_ms": dur(lambda s: s["actor"] == "presenter"),
            "router_ms": dur(lambda s: s["actor"] == "router"),
            "first_text_ms": self.meta.get("first_text_ms"),
            "total_ms": self.elapsed_ms(),
            "queued_ms": self.meta.get("queued_ms", 0),
            "llm_calls": len(self.meta["llm_calls"]),
            "boss_llm_calls": len(boss_llm),
            "boss_rounds": sum(s["actor"] == "boss" and not s["action"].endswith("_error") for s in self.steps),
            "tool_steps": len(self.worker_steps()),
            "answer_attempts": sum(s["action"] == "write_answer" for s in self.steps),
            **usage,
        }

    def worker_steps(self) -> list[dict]:
        return [s for s in self.steps if s["actor"].startswith("worker:")]

    def to_dict(self) -> dict:
        return {**self.meta, "finished": _now(), "timing": self.timing(), "steps": self.steps}

    def save(self, runs_dir: Path | None = None) -> dict:
        """Write JSON locally and to S3. Returns {"local": path, "s3": uri or None, "warning": ...}."""
        out = {"local": None, "s3": None, "warning": None}
        try:
            d = Path(runs_dir or RUNS_DIR)
            d.mkdir(parents=True, exist_ok=True)
            path = d / f"{self.run_id}.json"
            body = json.dumps(self.to_dict(), indent=1, default=str)
            path.write_text(body, encoding="utf-8")
            out["local"] = str(path)
            bucket = os.getenv("DATA_BUCKET")
            if bucket and os.getenv("TRACE_S3", "1") != "0":
                import boto3
                key = f"runs/{self.run_id}.json"
                boto3.client("s3", region_name="us-east-1").put_object(
                    Bucket=bucket, Key=key, Body=body.encode("utf-8"), ContentType="application/json")
                out["s3"] = f"s3://{bucket}/{key}"
        except Exception as e:
            out["warning"] = f"trace save failed: {e}"
        return out
