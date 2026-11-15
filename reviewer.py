"""Reviewer: deterministic quality gate (no LLM).

review_work(trace, plan, ...)  -> checks the workers' output before the presenter writes:
  1. the boss returned a plan with at least one recommended sector
  2. every target named in the question was analyzed (risk) and suitability-checked
  3. every recommended sector was analyzed, momentum-checked and suitability-checked
  4. the market context (cycle_phase) was evaluated
  5. every successful worker result has a source and a period
  6. every persona limit was evaluated
  7. no data dated after the analysis date
check_answer(text, trace) -> every number in the presenter's answer appears in the trace, cited steps exist.
Both return {"verdict": "pass" | "fail", "reasons": [...]}.
"""
import bisect
import re

from personas import PERSONAS
from workers import data_retriever as dr
from workers import risk_analyst as ra

# Plain-language words mapped to universe targets (team assumption; extend as needed)
ALIASES = {"crypto": "Crypto asset", "cryptocurrency": "Crypto asset", "bitcoin": "BTC-USD", "ethereum": "ETH-USD",
           "ether": "ETH-USD", "tech": "Information Technology", "technology": "Information Technology",
           "bond": "Bonds", "bonds": "Bonds", "gold": "Gold"}
RISK_ACTIONS = {"analyze_asset", "analyze_sector", "stress_test_2022"}
SMALL_INTS = set(range(0, 13))  # counts in prose ("3 asset classes", "12 months") need no source


def _verdict(reasons):
    return {"verdict": "fail" if reasons else "pass", "reasons": reasons}


def _norm(s):
    return str(s).strip().lower()


def extract_targets(question: str) -> list[str]:
    """Tickers / sector groups the question names (ticker, ticker without suffix, company name, group, alias)."""
    q = question.lower()
    words = set(re.findall(r"[a-z0-9&.\-]+", q))
    found = []
    universe = dr.get_universe().get("data", [])
    for r in universe:
        base = r["ticker"].lower().split(".")[0].split("-")[0]
        name = r["name"].lower().split(" (")[0]
        # ticker without suffix only when typed in capitals ("SHOP", not the word "shop")
        bare = len(base) >= 3 and re.search(rf"\b{re.escape(base.upper())}\b", question)
        if r["ticker"].lower() in words or bare or re.search(rf"\b{re.escape(name)}\b", q):
            found.append(r["ticker"])
    for g in {r["sector"].split(" (")[0] for r in universe}:
        if re.search(rf"\b{re.escape(g.lower())}\b", q):
            found.append(g)
    for word, target in ALIASES.items():
        if word in words:
            found.append(target)
    return list(dict.fromkeys(found))


def _steps(trace, action, ok_only=True):
    return [s for s in trace.worker_steps() if s["action"] == action
            and (not ok_only or (isinstance(s["output"], dict) and s["output"].get("status") == "ok"))]


def _target_of(step):
    i = step["input"] or {}
    return i.get("ticker") or i.get("sector") or i.get("target") or i.get("tickers_or_sector") or i.get("sector_or_ticker")


def review_work(trace, plan: dict | None, persona: str, question: str, as_of: str) -> dict:
    reasons = []
    plan = plan or {}
    recs = [r for r in plan.get("recommended_sectors") or [] if r]
    if not recs:
        reasons.append("boss plan has no recommended_sectors; recommend at least one sector group")

    risk_done = {_norm(_target_of(s)) for s in trace.worker_steps()
                 if s["action"] in RISK_ACTIONS and s["output"].get("status") == "ok"}
    suit_done = {_norm(_target_of(s)) for s in _steps(trace, "check_suitability")}
    mom_done = {_norm(_target_of(s)) for s in _steps(trace, "sector_momentum")}

    universe = dr.get_universe().get("data", [])
    valid = {_norm(r["ticker"]) for r in universe} | {_norm(r["sector"]) for r in universe} | {
        _norm(r["sector"].split(" (")[0]) for r in universe}
    requested = []
    for t in extract_targets(question) + list(plan.get("requested_targets") or []):
        if _norm(t) in valid:
            requested.append(t)
        else:
            reasons.append(f"plan target '{t}' is not an exact ticker or sector group name from list_sectors")
    for t in dict.fromkeys(requested):
        if _norm(t) not in risk_done:
            reasons.append(f"requested target '{t}' has no successful risk analysis (analyze_asset/analyze_sector)")
        if _norm(t) not in suit_done:
            reasons.append(f"requested target '{t}' has no successful check_suitability")
    for t in recs:
        if not ra.sector_members(t):
            reasons.append(f"recommended sector '{t}' is not a sector group of the universe (see list_sectors)")
            continue
        for done, tool_name in ((risk_done, "analyze_sector"), (suit_done, "check_suitability"),
                                (mom_done, "sector_momentum")):
            if _norm(t) not in done:
                reasons.append(f"recommended sector '{t}' is missing a successful {tool_name}")
    if not _steps(trace, "cycle_phase"):
        reasons.append("market context missing: call cycle_phase")

    esg = PERSONAS[persona.lower()]["esg_review_tickers"]
    checked = {m for s in _steps(trace, "check_suitability") for m in s["output"]["data"]["members"]}
    if esg and not set(esg) & checked:
        groups = sorted({r["sector"] for r in universe if r["ticker"] in esg})
        reasons.append(f"persona ESG-review names {esg} were not checked: call check_suitability on {groups}")

    limits = set(PERSONAS[persona.lower()]["limits"])
    for s in trace.worker_steps():
        out = s["output"] if isinstance(s["output"], dict) else {}
        if out.get("status") != "ok":
            continue
        if not out.get("source"):
            reasons.append(f"step {s['step']} ({s['action']}) has no source")
        if s["action"] != "list_sectors" and not out.get("period"):
            reasons.append(f"step {s['step']} ({s['action']}) has no period")
        end = (out.get("period") or {}).get("end")
        if end and end > as_of:
            reasons.append(f"step {s['step']} ({s['action']}) uses data up to {end}, after analysis date {as_of}")
        if s["action"] == "check_suitability":
            missing = limits - {c["rule"] for c in out["data"]["checks"]}
            if missing:
                reasons.append(f"step {s['step']} did not evaluate persona limits {sorted(missing)}")
    return _verdict(reasons)


# ---------- answer check ----------

NUM = re.compile(r"(?<![\w.])[-−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-−]?\d+(?:\.\d+)?")
STEP_REF = re.compile(r"\[fact:[^\]]*\]", re.I)


def _trace_numbers(obj, out):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.add(abs(float(obj)))
        out.add(abs(float(obj)) * 100)
    elif isinstance(obj, str):
        for m in NUM.findall(obj):
            out.add(abs(float(m.replace(",", "").replace("−", "-"))))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _trace_numbers(k, out)
            _trace_numbers(v, out)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            _trace_numbers(v, out)


def trace_numbers(trace) -> list[float]:
    nums = set()
    # not the whole meta: run_id / timestamps would make random digits look "supported"
    _trace_numbers([trace.meta["question"], trace.meta["analysis_date"]], nums)
    # evidence = worker results + the user step (question, persona profile). Never the boss plan or the
    # presenter's own draft, or an answer would "support" its own numbers.
    _trace_numbers([{k: s[k] for k in ("input", "output")} for s in trace.steps
                    if s["actor"].startswith("worker:") or s["actor"] == "user"], nums)
    return sorted(nums)


def check_answer(text: str, trace) -> dict:
    """Every number in the answer must match a trace number (as written, or x100 for fractions) within its
    rounding; [fact: step N] citations must point to existing steps."""
    reasons = []
    n_steps = len(trace.steps)
    for ref in STEP_REF.findall(text):
        for n in re.findall(r"\d+", ref):
            if not 1 <= int(n) <= n_steps:
                reasons.append(f"citation {ref} points to step {n}, but the trace has {n_steps} steps")
    body = STEP_REF.sub(" ", text)
    known = trace_numbers(trace)
    bad = []
    for m in NUM.findall(body):
        raw = m.replace(",", "").replace("−", "-")
        x = abs(float(raw))
        if x in SMALL_INTS:
            continue
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        tol = 0.5 * 10 ** -decimals + 1e-9
        i = bisect.bisect_left(known, x - tol)
        if not (i < len(known) and known[i] <= x + tol):
            bad.append(m)
    if bad:
        reasons.append(f"numbers not found in the trace: {sorted(set(bad))}")
    return _verdict(reasons)
