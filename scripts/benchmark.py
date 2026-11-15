"""Latency benchmark on REAL Bedrock (costs money): the benchmark question + the 3 demo questions.

    python scripts/benchmark.py --label before --out reports/bench_before.json
    BOSS_MODEL=global.anthropic.claude-haiku-4-5-20251001-v1:0 python scripts/benchmark.py --label haiku
    python scripts/benchmark.py --table reports/bench_before.json reports/bench_after.json

Each question runs in its own process (the pipeline keeps the active trace in a process-wide context), in
parallel. Prints one row per question with the trace timing summary, and checks each plan.
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = [
    ("amira", "Best industry for the quickest gains"),
    ("robert", "I want to put a big part of my savings in NVDA, good idea?"),
    ("amira", "I only want AI and crypto, which industry should I focus on?"),
    ("mateo", "Which industry gives balanced growth for me?"),
]
COLUMNS = [("boss_turns_ms", "boss turns"), ("boss_plan_ms", "boss plan"), ("tools_ms", "tools"),
           ("reviewer_ms", "reviewer"), ("presenter_ms", "presenter"), ("first_text_ms", "1st text"),
           ("total_ms", "total"), ("llm_calls", "LLM calls")]


def plan_checks(persona: str, question: str, r: dict) -> list[str]:
    """What a correct plan must contain (the reviewer verdicts plus the demo-question expectations)."""
    import reviewer
    problems = []
    plan, trace = r["plan"] or {}, r["trace"]
    recs = plan.get("recommended_sectors") or []
    if r["work_verdict"]["verdict"] != "pass":
        problems.append(f"work: {r['work_verdict']['reasons']}")
    if r["answer_verdict"]["verdict"] != "pass":
        problems.append(f"answer: {r['answer_verdict']['reasons']}")
    if reviewer.check_answer(r["answer"], trace, lang="en")["verdict"] != "pass":
        problems.append("check_answer failed on the final answer")
    if not r["answer"].lstrip().lower().startswith(("## summary", "*demo")):
        problems.append("answer does not start with ## Summary")
    suit = [s for s in trace.steps if s["action"] == "check_suitability" and s["output"].get("status") == "ok"]
    blocks = {"Bonds", "Broad market"}
    if persona in ("amira", "mateo", "robert") and not blocks & set(recs):
        problems.append(f"no Bonds / Broad market building block in {recs}")
    if persona == "robert":
        if not any(s["input"]["target"] == "NVDA" and s["output"]["data"]["overall"] in ("conflict", "flag")
                   for s in suit):
            problems.append("NVDA not challenged")
        if {"NVDA", "Information Technology"} & set(recs):
            problems.append(f"recommends {recs}")
    if persona == "mateo":
        flagged = {t for s in suit for c in s["output"]["data"]["checks"]
                   if c["rule"] == "esg_review" and c["status"] == "flag" for t in c["value"]}
        if not flagged & {"ENB.TO", "CNQ.TO", "XOM"}:
            problems.append("energy names not flagged for ESG review")
    if any(s["output"]["data"]["overall"] == "conflict" for s in suit if s["input"]["target"] in recs
           and s["input"].get("proposed_weight") is None):
        problems.append("recommends a group with a conflict")
    return problems


def one(persona: str, question: str, warm: bool = False) -> dict:
    """Run in a child process: one question through the real pipeline. warm = run the server's start-up
    warm-up first (not timed), like a server that has been up for a few seconds."""
    sys.path.insert(0, str(ROOT))
    import pipeline
    if warm and hasattr(__import__("agent_tools"), "warm_up"):
        __import__("agent_tools").warm_up(as_of=pipeline.ANALYSIS_DATE)
    r = pipeline.ChatSession(persona).ask(question)
    return {"persona": persona, "question": question, "timing": r["timing"],
            "recommended": (r["plan"] or {}).get("recommended_sectors"), "problems": plan_checks(persona, question, r),
            "llm_calls": r["trace"].meta["llm_calls"], "usage": r["trace"].meta["llm_usage"],
            "boss_model": pipeline.BOSS_MODEL, "presenter_model": os.getenv("PRESENTER_MODEL") or __import__(
                "presenter").PRESENTER_MODEL, "run_id": r["trace"].run_id, "answer": r["answer"]}


def child(i: int, warm: bool = False) -> dict:
    out = subprocess.run([sys.executable, __file__, "--one", str(i)] + (["--warm"] if warm else []), cwd=ROOT,
                         capture_output=True, text=True, timeout=900)
    try:
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return {"persona": QUESTIONS[i][0], "question": QUESTIONS[i][1], "error": (out.stderr or out.stdout)[-1500:]}


def fmt(v, key):
    if v is None:
        return "-"
    return f"{v / 1000:.1f}s" if key.endswith("_ms") else str(v)


def table(rows: list[dict], label: str) -> str:
    head = f"| {label} | " + " | ".join(c[1] for c in COLUMNS) + " | plan |"
    lines = [head, "|" + "---|" * (len(COLUMNS) + 2)]
    for r in rows:
        name = f"{r['persona']}: {r['question'][:34]}"
        if "error" in r:
            lines.append(f"| {name} | " + " | ".join("-" for _ in COLUMNS) + f" | ERROR {r['error'][-80:]!r} |")
            continue
        ok = "ok" if not r["problems"] else "; ".join(r["problems"])[:120]
        lines.append(f"| {name} | " + " | ".join(fmt(r["timing"].get(k), k) for k, _ in COLUMNS) + f" | {ok} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", type=int)
    ap.add_argument("--label", default="run")
    ap.add_argument("--out")
    ap.add_argument("--only", type=int, nargs="*", help="question indexes to run")
    ap.add_argument("--warm", action="store_true", help="warm the tool cache first (server steady state)")
    ap.add_argument("--table", nargs="*", help="print tables from saved JSON files")
    a = ap.parse_args()
    if a.one is not None:
        print(json.dumps(one(*QUESTIONS[a.one], warm=a.warm), default=str))
        return
    if a.table:
        for f in a.table:
            d = json.loads(Path(f).read_text())
            print(f"\n{d['label']}  (boss {d['rows'][0].get('boss_model', '?')}, presenter "
                  f"{d['rows'][0].get('presenter_model', '?')})\n" + table(d["rows"], d["label"]))
        return
    idx = a.only if a.only else range(len(QUESTIONS))
    with ThreadPoolExecutor(len(list(idx))) as ex:
        rows = list(ex.map(lambda i: child(i, a.warm), idx))
    print(table(rows, a.label))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps({"label": a.label, "warm": a.warm, "rows": rows}, indent=1, default=str))


if __name__ == "__main__":
    main()
