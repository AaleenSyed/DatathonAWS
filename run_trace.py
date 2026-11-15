"""Run trace: every step of one question (who did what, with which input and output). The explainability evidence.

Saved as JSON in runs/<run_id>.json and, when DATA_BUCKET is set (and TRACE_S3 != "0"), to
s3://$DATA_BUCKET/runs/<run_id>.json. Saving never raises; a failed upload is recorded in the trace.
"""
import json
import os
import threading
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
    def __init__(self, persona: str, question: str, as_of: str, turn: int = 1, session_id: str | None = None):
        self.run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
        self.meta = {"run_id": self.run_id, "session_id": session_id, "turn": turn, "persona": persona,
                     "question": question, "analysis_date": as_of, "started": _now()}
        self.steps: list[dict] = []
        self._lock = threading.Lock()  # Strands may run tools concurrently; step numbers must stay unique

    def add(self, actor: str, action: str, input=None, output=None) -> int:
        """Append a step and return its number (1-based), which answers cite as [fact: step N]."""
        with self._lock:
            n = len(self.steps) + 1
            self.steps.append({"step": n, "actor": actor, "action": action, "input": input, "output": output,
                               "output_summary": _summary(output), "timestamp": _now()})
        return n

    def worker_steps(self) -> list[dict]:
        return [s for s in self.steps if s["actor"].startswith("worker:")]

    def to_dict(self) -> dict:
        return {**self.meta, "finished": _now(), "steps": self.steps}

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
