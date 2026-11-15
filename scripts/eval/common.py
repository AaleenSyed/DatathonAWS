"""Shared code for the evaluation scripts (scripts/eval/). Uses the REAL Bedrock pipeline; app code is not changed.

- Prices: Bedrock on-demand, global cross-region inference profiles, USD per 1M tokens (see PRICES).
- Budget: every script adds up the estimated spend of ALL eval result files (one shared ledger) and stops
  submitting work once spend + the cost of the runs in flight would pass --budget-usd.
- Resume: each script appends one JSON line per finished item to reports/eval/raw/<name>.jsonl and skips ids
  already done. Errors are not "done": they are retried on the next start.
- Concurrency: --concurrency worker processes (default 4). The pipeline keeps its active trace in a
  process-wide context, so pipeline runs need one process each; every worker runs its items one at a time.
- Throttling: boto3 adaptive retries inside the app, plus up to 4 whole-run retries with exponential backoff
  when a run hit throttling anyway.
"""
import argparse
import concurrent.futures as cf
import csv
import json
import multiprocessing as mp
import os
import random
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = ROOT / "reports" / "eval"
LABEL = "baseline"
OUT = EVAL_ROOT / LABEL          # CSVs of the current run label
RAW = OUT / "raw"                # one JSONL per script (resume + ledger)
DOCS = ROOT / "docs"


def set_label(label: str):
    """Results of different runs (e.g. "smoke", "baseline") live in reports/eval/<label>/."""
    global LABEL, OUT, RAW
    if not label or not all(ch.isalnum() or ch in "-_" for ch in label):
        raise SystemExit(f"invalid --label {label!r}")
    LABEL, OUT = label, EVAL_ROOT / label
    RAW = OUT / "raw"
sys.path.insert(0, str(ROOT))

# USD per 1M tokens, Bedrock on-demand, global cross-region inference profiles (same list price as the Claude
# API; regional profiles cost 10% more). Sources: Anthropic / AWS list prices as published Nov 2026.
PRICES = {
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": (1.0, 5.0),
    "global.anthropic.claude-sonnet-4-6": (3.0, 15.0),
    "global.anthropic.claude-sonnet-5": (2.0, 10.0),
    "global.anthropic.claude-opus-5-5": (4.0, 20.0),
}
# Bedrock Guardrails: about $0.15 per 1,000 text units (1 unit = up to 1,000 characters) per policy type;
# the guardrail uses ~3 (content, denied topics, PII). Prompt-attack is part of content filters.
GUARDRAIL_USD_PER_UNIT = 3 * 0.15 / 1000
JUDGE_MODEL = "global.anthropic.claude-opus-5-5"


def guardrail_from_env() -> tuple | None:
    """(GUARDRAIL_ID, GUARDRAIL_VERSION) from .env, the same guardrail the app uses; None when unset."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    gid = os.getenv("GUARDRAIL_ID", "").strip()
    return (gid, os.getenv("GUARDRAIL_VERSION", "DRAFT").strip() or "DRAFT") if gid else None
THROTTLE = re.compile(r"Throttl|TooManyRequests|Too many requests|ServiceUnavailable|ModelNotReady|"
                      r"serviceUnavailable|rate exceeded", re.I)


def usd(model: str, tokens_in: int, tokens_out: int) -> float:
    p_in, p_out = PRICES.get(model, (4.0, 20.0))  # unknown model: assume the most expensive used here
    return tokens_in / 1e6 * p_in + tokens_out / 1e6 * p_out


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- results, resume, budget ----------

_write_lock = threading.Lock()


def raw_path(name: str) -> Path:
    return RAW / f"{name}.jsonl"


def load(name: str) -> dict:
    """id -> latest record (later lines win), for one result file."""
    out = {}
    p = raw_path(name)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["id"]] = r
    return out


def append(name: str, record: dict):
    RAW.mkdir(parents=True, exist_ok=True)
    line = scrub(json.dumps(record, ensure_ascii=False, default=str))  # never store env values or credentials
    with _write_lock, raw_path(name).open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def done_ids(name: str) -> set:
    return {i for i, r in load(name).items() if r.get("status") == "ok"}


def _records(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["id"]] = r
    return out


def total_spend(label: str | None = None) -> float:
    """Estimated USD spent by the eval runs so far: every label (the budget is global), or one label."""
    total = 0.0
    paths = (EVAL_ROOT / label / "raw").glob("*.jsonl") if label else EVAL_ROOT.glob("*/raw/*.jsonl")
    for p in paths:
        for r in _records(p).values():
            total += float(r.get("cost_usd") or 0) + sum(float(a.get("cost_usd") or 0) for a in r.get("attempts", []))
    return total


class Budget:
    """Shared spend limit. reserve() before starting an item (with a pessimistic estimate); settle() after."""

    def __init__(self, limit: float, estimate: float):
        self.limit, self.estimate = limit, estimate
        self.spent = total_spend()
        self.in_flight = 0.0
        self.lock = threading.Lock()

    def reserve(self) -> bool:
        with self.lock:
            if self.spent + self.in_flight + self.estimate > self.limit:
                return False
            self.in_flight += self.estimate
            return True

    def settle(self, cost: float):
        with self.lock:
            self.in_flight -= self.estimate
            self.spent += cost
            n = getattr(self, "_n", 0) + 1
            self._n = n
            # adapt the estimate to what runs really cost (keep it pessimistic)
            self.estimate = max(self.estimate * 0.8 + cost * 0.2, cost)


def base_args(desc: str, n_default: int) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--n", type=int, default=n_default, help="number of items (resumes: done items are skipped)")
    ap.add_argument("--budget-usd", type=float, default=400.0, help="stop when the estimated total eval spend reaches this")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--no-guardrail", action="store_true", help="run without the Bedrock Guardrail")
    ap.add_argument("--no-upload", action="store_true", help="do not upload results to S3")
    ap.add_argument("--label", default="baseline", help="results go to reports/eval/<label>/")
    return ap


def parse(ap: argparse.ArgumentParser):
    a = ap.parse_args()
    set_label(a.label)
    return a


def run_pool(name: str, items: list[dict], work, budget: Budget, concurrency: int, processes: bool, init=None,
             init_args=()):
    """Run work(item) for every item not done yet, at most `concurrency` at a time, within the budget.
    work returns a record dict with "status" and "cost_usd". Prints one line per item."""
    todo = [it for it in items if it["id"] not in done_ids(name)]
    print(f"[{name}] {len(items)} items, {len(items) - len(todo)} already done, {len(todo)} to run; "
          f"spend so far ${budget.spent:.2f} of ${budget.limit:.2f}", flush=True)
    if not todo:
        return
    if processes:
        ex = cf.ProcessPoolExecutor(concurrency, mp_context=mp.get_context("spawn"), initializer=init, initargs=init_args)
    else:
        ex = cf.ThreadPoolExecutor(concurrency)
    stopped, pending, queue, t0, finished = False, {}, list(todo), time.time(), 0
    with ex:
        while queue or pending:
            while queue and len(pending) < concurrency and not stopped:
                if not budget.reserve():
                    stopped = True
                    print(f"[{name}] budget reached (${budget.spent:.2f} + in flight): not starting more", flush=True)
                    break
                it = queue.pop(0)
                pending[ex.submit(work, it)] = it
            if not pending:
                break
            done, _ = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
            for fut in done:
                it = pending.pop(fut)
                try:
                    rec = fut.result()
                except Exception as e:  # a crashed worker: record the error, retry on the next start
                    rec = {"id": it["id"], "status": "error", "error": f"{type(e).__name__}: {str(e)[:300]}", "cost_usd": 0}
                rec.setdefault("id", it["id"])
                rec.setdefault("finished", now())
                append(name, rec)
                budget.settle(float(rec.get("cost_usd") or 0))
                finished += 1
                rate = finished / max(time.time() - t0, 1e-9)
                print(f"[{name}] {finished}/{len(todo)} {it['id']} {rec.get('status')} "
                      f"{rec.get('summary', '')} | ${rec.get('cost_usd', 0):.4f} | spend ${budget.spent:.2f} | "
                      f"eta {((len(todo) - finished) / rate) / 60:.0f} min", flush=True)
            if stopped and not pending:
                break


def env_values() -> list[str]:
    """Values from .env and the AWS credentials in the environment that must never appear in exported files."""
    vals = []
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                v = line.split("=", 1)[1].strip().strip("\"'")
                if len(v) >= 6:
                    vals.append(v)
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        if len(os.getenv(k, "")) >= 6:
            vals.append(os.environ[k])
    return vals


SECRET_PATTERNS = re.compile(r"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|aws_secret_access_key|-----BEGIN [A-Z ]*PRIVATE KEY")


def scrub(text: str) -> str:
    for v in env_values():
        text = text.replace(v, "[redacted]")
    return SECRET_PATTERNS.sub("[redacted]", text)


def scan(paths: list[Path]) -> list[str]:
    """Files under `paths` that contain an env value or a credential pattern (should be empty)."""
    vals = env_values()
    bad = []
    for p in paths:
        for f in ([p] if p.is_file() else [x for x in p.rglob("*") if x.is_file()]):
            t = f.read_text(encoding="utf-8", errors="ignore")
            hits = [v[:4] + "…" for v in vals if v in t] + (["credential pattern"] if SECRET_PATTERNS.search(t) else [])
            if hits:
                bad.append(f"{f.relative_to(ROOT)}: {hits}")
    return bad


def write_csv(path: Path, rows: list[dict], columns: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: scrub(json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v))
                        if v is not None else "" for k, v in r.items()})


def upload(paths: list[Path]):
    """Copy result files to s3://$DATA_BUCKET/runs/eval/<file> (the app's run-trace prefix)."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    bucket = os.getenv("DATA_BUCKET")
    if not bucket:
        print("upload skipped: DATA_BUCKET is not set")
        return
    import boto3
    s3 = boto3.client("s3", region_name="us-east-1")
    for p in paths:
        if p.exists():
            rel = p.relative_to(ROOT).as_posix()
            key = "runs/eval/" + (rel.replace("reports/eval/", "") if rel.startswith("reports/eval/") else f"{LABEL}/{p.name}")
            s3.upload_file(str(p), bucket, key)
    print(f"uploaded {len([p for p in paths if p.exists()])} files to s3://{bucket}/runs/eval/")


# ---------- profiles ----------

# 3 fixed questionnaire answer sets (one per non-built-in risk shape), registered in every worker process.
CUSTOM = {
    "custom-low": dict(goal="preserve", horizon="lt3", drop25="sell_all", liquidity="high", crypto="small",
                       esg="strict", industries=["Utilities"]),
    "custom-moderate": dict(goal="balanced", horizon="5to10", drop25="hold", liquidity="low", crypto="small",
                            esg="prefer", industries=["Health Care", "Financials"]),
    "custom-high": dict(goal="growth", horizon="10plus", drop25="buy_more", liquidity="none", crypto="significant",
                        esg="not_important", industries=["Information Technology", "Consumer Discretionary"]),
}
PROFILES = ["amira", "mateo", "robert", *CUSTOM]
_keys: dict = {}


def init_worker(guardrail: tuple | None, extra_env: dict | None = None):
    """Worker process start: environment, custom profiles, warm tool cache."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    os.environ["TRACE_S3"] = "0"          # traces stay in runs/; result files are uploaded at the end
    os.environ.pop("AGENT_MODE", None)    # always the real Bedrock pipeline
    if guardrail:
        os.environ["GUARDRAIL_ID"], os.environ["GUARDRAIL_VERSION"] = guardrail
    else:
        os.environ.pop("GUARDRAIL_ID", None)
    for k, v in (extra_env or {}).items():
        os.environ[k] = v
    import agent_tools
    import pipeline
    import profile_builder
    for label, answers in CUSTOM.items():
        _keys[label] = profile_builder.register(answers, owner="eval")
    agent_tools.warm_up(as_of=pipeline.ANALYSIS_DATE)


def persona_key(label: str) -> str:
    return _keys.get(label, label)


def run_pipeline(item: dict, presenter_model: str | None = None, presenter_max_tokens: int | None = None) -> dict:
    """One question through the real pipeline (in a worker process). Returns a flat metrics record."""
    import pipeline
    import presenter
    import reviewer
    if presenter_model:
        presenter.PRESENTER_MODEL = presenter_model
    if presenter_max_tokens:
        presenter.MAX_TOKENS = presenter_max_tokens
    attempts = []
    for attempt in range(4):
        t0 = time.perf_counter()
        r = pipeline.ChatSession(persona_key(item["profile"]), lang=item["lang"]).ask(item["question"])
        wall = time.perf_counter() - t0
        trace = r["trace"]
        rec = metrics(item, r, wall, presenter.PRESENTER_MODEL, pipeline.BOSS_MODEL)
        errors = [str(s["output"]) for s in trace.steps if s["action"].endswith("_error")
                  or (isinstance(s["output"], dict) and "presenter error" in str(s["output"].get("reasons", "")))]
        if not any(THROTTLE.search(e) for e in errors):
            rec["attempts"] = attempts
            rec["throttle_retries"] = len(attempts)
            return rec
        attempts.append({"cost_usd": rec["cost_usd"], "error": errors[0][:200]})
        time.sleep(min(60, 4 * 2 ** attempt) * (0.5 + random.random()))
    rec["status"], rec["error"], rec["attempts"] = "error", "throttled after 4 attempts", attempts[:-1]
    return rec


NOT_FOUND = re.compile(r"numbers not found[^\[]*\[([^\]]*)\]")


def metrics(item: dict, r: dict, wall: float, presenter_model: str, boss_model: str) -> dict:
    import reviewer
    trace = r["trace"]
    tm = trace.timing()
    usage = {"boss": [0, 0], "presenter": [0, 0]}
    for u in trace.meta.get("llm_usage", []):
        usage.setdefault(u["role"], [0, 0])
        usage[u["role"]][0] += int(u.get("inputTokens") or 0)
        usage[u["role"]][1] += int(u.get("outputTokens") or 0)
    guard = [s for s in trace.steps if s["actor"] == "guardrail"]
    # 1 text unit = up to 1,000 characters; the trace keeps only 500 characters, so size the checks from the source
    sizes = {"INPUT": len(item["question"]), "OUTPUT": len(r["answer"])}
    units = sum(max(1, -(-sizes.get((s["input"] or {}).get("source"), 500) // 1000)) for s in guard)
    cost = usd(boss_model, *usage["boss"]) + usd(presenter_model, *usage["presenter"]) + units * GUARDRAIL_USD_PER_UNIT
    checks = [s["output"] for s in trace.steps if s["action"] == "check_answer"]
    flagged_first = NOT_FOUND.findall("; ".join(checks[0].get("reasons", []))) if checks else []
    flagged_final = NOT_FOUND.findall("; ".join(checks[-1].get("reasons", []))) if checks else []
    final = next((s["output"] for s in reversed(trace.steps) if s["action"] == "final_answer"), {}) or {}
    blocked = final.get("blocked_by")
    plan = r.get("plan") or {}
    suit = [s for s in trace.steps if s["action"] == "check_suitability" and s["output"].get("status") == "ok"]
    rec_conflict = any(s["output"]["data"]["overall"] == "conflict" for s in suit
                       if s["input"]["target"] in (plan.get("recommended_sectors") or [])
                       and s["input"].get("proposed_weight") is None)
    lang = item["lang"]
    return {
        "id": item["id"], "status": "ok", "profile": item["profile"], "lang": lang, "template": item.get("template"),
        "category": item.get("category"), "question": item["question"], "run_id": trace.run_id,
        "boss_model": boss_model, "presenter_model": presenter_model,
        "wall_s": round(wall, 2), "total_ms": tm["total_ms"], "first_text_ms": tm["first_text_ms"],
        "boss_ms": tm["boss_ms"], "presenter_ms": tm["presenter_ms"], "llm_calls": tm["llm_calls"],
        "boss_in": usage["boss"][0], "boss_out": usage["boss"][1],
        "presenter_in": usage["presenter"][0], "presenter_out": usage["presenter"][1],
        "guardrail_units": units, "cost_usd": round(cost, 6),
        "work_verdict": r["work_verdict"]["verdict"], "answer_verdict": r["answer_verdict"]["verdict"],
        "answer_attempts": tm["answer_attempts"],
        "first_check": checks[0]["verdict"] if checks else None,
        "numbers_flagged_first": len([x for x in ",".join(flagged_first).split(",") if x.strip()]),
        "numbers_flagged_final": len([x for x in ",".join(flagged_final).split(",") if x.strip()]),
        "recheck": reviewer.check_answer(r["answer"], trace, lang=lang)["verdict"] if not blocked else "blocked",
        "guardrail_blocked": blocked or "", "recommended": plan.get("recommended_sectors") or [],
        "recommends_conflict": rec_conflict, "starts_with_summary": r["answer"].lstrip().lower().startswith(("## summary", "## résumé")),
        "answer": r["answer"],
        "summary": f"{item['profile']} {tm['total_ms'] / 1000:.1f}s work={r['work_verdict']['verdict']} "
                   f"answer={r['answer_verdict']['verdict']}{' BLOCKED ' + blocked if blocked else ''}",
    }


# ---------- questions ----------

TICKERS = ["NVDA", "TSLA", "AAPL", "SHOP.TO", "ENB.TO", "XOM", "BTC-USD", "JPM", "FTS.TO", "RY.TO", "MSFT", "AMZN"]
SECTORS = ["Information Technology", "Energy", "Utilities", "Consumer Staples", "Health Care", "Financials",
           "Bonds", "Consumer Discretionary"]
SECTORS_FR = {"Information Technology": "les technologies de l’information", "Energy": "l’énergie",
              "Utilities": "les services publics", "Consumer Staples": "les biens de consommation de base",
              "Health Care": "la santé", "Financials": "les services financiers", "Bonds": "les obligations",
              "Consumer Discretionary": "la consommation discrétionnaire"}
TEMPLATES = {
    "en": [
        ("weight", "Can I put {pct}% of my savings in {ticker}?"),
        ("big_share", "I want to put a big part of my savings in {ticker}, good idea?"),
        ("sector_risk", "Is {sector} too risky for me?"),
        ("best_fit", "Which industry fits my profile best?"),
        ("quick_gains", "Best industry for the quickest gains"),
        ("crypto_cap", "How much crypto can I hold at most?"),
        ("balanced", "Which industry gives balanced growth for me?"),
        ("avoid", "Should I avoid {sector}?"),
        ("compare", "Compare {sector} and {sector2} for my profile."),
        ("stress", "What would a 2022-style crash do to {ticker} for me?"),
        ("only", "I only want {sector}, which industry should I focus on?"),
        ("income", "Where should I look for steady, lower-risk growth?"),
    ],
    "fr": [
        ("weight", "Puis-je placer {pct} % de mes économies dans {ticker}?"),
        ("sector_risk", "Est-ce que {sector_fr} sont trop risqués pour moi?"),
        ("best_fit", "Quelle industrie convient le mieux à mon profil?"),
        ("quick_gains", "Meilleure industrie pour les gains les plus rapides"),
        ("crypto_cap", "Combien de cryptos puis-je détenir au maximum?"),
        ("big_share", "Je veux mettre une grande partie de mes économies dans {ticker}, bonne idée?"),
    ],
}
FR_SHARE = 0.2


def questions(n: int, seed: int, prefix: str) -> list[dict]:
    """Deterministic questions: profiles in turn, ~20% French. The first k of a larger n are the same as n=k,
    so a smoke test counts toward the full run."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        lang = "fr" if rng.random() < FR_SHARE else "en"
        tpl_name, tpl = rng.choice(TEMPLATES[lang])
        s1, s2 = rng.sample(SECTORS, 2)
        q = tpl.format(pct=rng.choice([5, 10, 20, 40, 60]), ticker=rng.choice(TICKERS), sector=s1, sector2=s2,
                       sector_fr=SECTORS_FR[s1])
        out.append({"id": f"{prefix}{i + 1:04d}", "profile": PROFILES[i % len(PROFILES)], "lang": lang,
                    "template": tpl_name, "question": q})
    return out


def pct(values, q) -> float | None:
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)
