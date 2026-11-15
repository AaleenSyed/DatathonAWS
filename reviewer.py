"""Reviewer: deterministic quality gate (no LLM).

review_work(trace, plan, ...)  -> checks the workers' output before the presenter writes:
  1. the boss returned a plan with at least one recommended sector
  2. every target named in the question was analyzed (risk) and suitability-checked
  3. every recommended sector was analyzed, momentum-checked and suitability-checked
  4. the market context (cycle_phase) was evaluated
  5. every successful worker result has a source and a period
  6. every persona limit was evaluated
  7. no data dated after the analysis date
check_answer(text, trace) -> every number in the presenter's answer appears in the trace, cited steps exist,
  and no sentence promises or predicts returns ("guaranteed", "will go up", "safe bet", "sans risque", ...).
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
RISK_ACTIONS = {"analyze_asset", "analyze_sector"}  # a stress test alone is not a risk analysis
SMALL_INTS = set(range(0, 13))  # bare counts in prose ("3 asset classes", "12 months") need no source


def _verdict(reasons):
    return {"verdict": "fail" if reasons else "pass", "reasons": reasons}


def _norm(s):
    return str(s).strip().lower()


def extract_targets(question: str) -> list[str]:
    """Tickers / sector groups the question names (ticker, ticker without suffix, company name, group, alias)."""
    q = question.lower()
    words = {w.strip(".-") for w in re.findall(r"[a-z0-9&.\-]+", q)}
    found = []
    universe = dr.get_universe().get("data", [])
    for r in universe:
        base = r["ticker"].lower().split(".")[0].split("-")[0]
        name = r["name"].lower().split(" (")[0]
        # ticker without suffix only when typed in capitals ("SHOP", not the word "shop")
        bare = len(base) >= 2 and re.search(rf"\b{re.escape(base.upper())}\b", question)
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
    t = (i.get("ticker") or i.get("sector") or i.get("target") or i.get("tickers_or_sector")
         or i.get("sector_or_ticker") or i.get("tickers"))
    return " ".join(sorted(t)) if isinstance(t, (list, tuple)) else t


def _named_in(name, notes: str) -> bool:
    """Whole-word match of a target name in the boss's notes ("AI" must not match "fails")."""
    return bool(name) and re.search(rf"(?<![\w.-]){re.escape(_norm(name))}(?![\w-])", notes) is not None


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
    notes = _norm(" ".join([plan.get("reasoning_notes") or ""] + list(plan.get("conflicts_found") or [])))
    for t in extract_targets(question) + list(plan.get("requested_targets") or []):
        if _norm(t) in valid:
            requested.append(t)
        elif not _named_in(t, notes):  # outside the universe is fine if the boss says so in its notes
            reasons.append(f"plan target '{t}' is not an exact ticker or sector group name from list_sectors "
                           "(if it is outside the universe, say so in reasoning_notes)")
    for t in dict.fromkeys(requested):
        if _norm(t) not in risk_done:
            reasons.append(f"requested target '{t}' has no successful risk analysis (analyze_asset/analyze_sector)")
        if _norm(t) not in suit_done:
            reasons.append(f"requested target '{t}' has no successful check_suitability")
    for t in recs:
        if not ra.sector_members(t):
            reasons.append(f"recommended sector '{t}' is not a sector group of the universe (see list_sectors)")
            continue
        sector_done = {_norm(_target_of(s)) for s in _steps(trace, "analyze_sector")}
        for done, tool_name in ((sector_done, "analyze_sector"), (suit_done, "check_suitability"),
                                (mom_done, "sector_momentum")):
            if _norm(t) not in done:
                reasons.append(f"recommended sector '{t}' is missing a successful {tool_name}")
        checks = [s for s in _steps(trace, "check_suitability") if _norm(_target_of(s)) == _norm(t)]
        unweighted = [s for s in checks if (s["input"] or {}).get("proposed_weight") is None]
        latest = (unweighted or checks)[-1:] if checks else []
        if latest and latest[0]["output"]["data"].get("overall") == "conflict":
            reasons.append(f"recommended sector '{t}' has a suitability conflict with the persona; recommend "
                           "groups that fit")
    if not _steps(trace, "cycle_phase"):
        reasons.append("market context missing: call cycle_phase")

    esg = PERSONAS[persona.lower()]["esg_review_tickers"]
    checked = {m for s in _steps(trace, "check_suitability") for m in s["output"]["data"]["members"]}
    unchecked = [t for t in esg if t not in checked]
    if unchecked:
        groups = sorted({r["sector"] for r in universe if r["ticker"] in unchecked})
        reasons.append(f"persona ESG-review names {unchecked} were not checked: call check_suitability on {groups}")

    limits = set(PERSONAS[persona.lower()]["limits"])
    for s in trace.worker_steps():
        out = s["output"] if isinstance(s["output"], dict) else {}
        if out.get("status") != "ok":  # AGENT_GUARDRAILS 4.5: retried successfully or explained
            target = _target_of(s)
            plan_targets = {_norm(x) for x in requested + recs}
            fixed = any(o["action"] == s["action"] and o["step"] > s["step"] and o["output"].get("status") == "ok"
                        and target and (_norm(_target_of(o)) == _norm(target) or _norm(_target_of(o)) in plan_targets)
                        for o in trace.worker_steps())
            explained = bool(target) and all(_named_in(x, notes) for x in str(target).split())
            if not fixed and not explained:
                reasons.append(f"step {s['step']} ({s['action']} {target}) returned an error that was neither "
                               "retried successfully nor explained in reasoning_notes")
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
STEP_REF = re.compile(r"\[[^\]]*\bfact:[^\]]*\]", re.I)
# "...51.1% [fact: step 2]. XBB.TO vol ..." splits here; also French capitals ("À", "É") and guillemets
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ*_\-(«])")
YEAR = re.compile(r"^(19|20)\d\d$")
FR_DECIMAL = re.compile(r"(?<=\d),(?=\d)")  # 51,1 -> 51.1
FR_THOUSANDS = re.compile(r"(?<=\d)[\u00a0\u202f](?=\d{3}\b)")  # 1 254 (non-breaking space) -> 1254


def normalize_numbers(text: str, lang: str = "en") -> str:
    """French answers write 51,1 % and 1 254; turn them into 51.1 % and 1254 before checking numbers.
    Citation tags are left alone (they are removed before numbers are read)."""
    if lang != "fr":
        return text
    return FR_DECIMAL.sub(".", FR_THOUSANDS.sub("", text))


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


def _evidence(step) -> bool:
    # worker results + the user step (question, persona profile). Never the boss plan or the presenter's own
    # draft, or an answer would "support" its own numbers.
    return step["actor"].startswith("worker:") or step["actor"] == "user"


def trace_numbers(trace, steps=None) -> list[float]:
    nums = set()
    # not the whole meta: run_id / timestamps would make random digits look "supported"
    _trace_numbers([trace.meta["question"], trace.meta["analysis_date"]], nums)
    _trace_numbers([{k: s[k] for k in ("input", "output")} for s in (steps if steps is not None else trace.steps)
                    if _evidence(s)], nums)
    return sorted(nums)


def _unsupported(text: str, known: list[float]) -> list[str]:
    bad = []
    for m in NUM.finditer(text):
        raw = m.group().replace(",", "").replace("−", "-")
        x = abs(float(raw))
        is_pct = re.match(r"\s*%", text[m.end():]) is not None
        # "5x", "5×", "5 times": a calculated multiple, not a count
        is_multiple = re.match(r"\s*(?:x\b|×|times\b)", text[m.end():], re.I) is not None
        if x in SMALL_INTS and "." not in raw and not raw.startswith("-") and not is_pct and not is_multiple:
            continue  # bare count like "3 asset classes"; "9%", "9 %", "5x" or "5.0" must still be found
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        tol = 0.5 * 10 ** -decimals + 1e-9
        i = bisect.bisect_left(known, x - tol)
        if not (i < len(known) and known[i] <= x + tol):
            bad.append(m.group())
    return bad


# Certainty about future returns (guardrails/05_presenter.md). English and Canadian French. A negation shortly
# before the match ("not guaranteed", "n'est pas garanti", "aucun placement n'est sans risque") is fine.
PREDICTION = re.compile(
    r"\bguarantee[sd]?\b|\bwill\s+(?:surely\s+|certainly\s+|definitely\s+)?(?:go\s+up|rise|double|triple|soar)\b"
    r"|\bsafe\s+bet\b|\bcan(?:not|'t|’t)\s+lose\b|\bsure\s+thing\b"
    r"|\bgaranti(?:e|s|es)?\b|\bsans\s+risque\b|\bva(?:\s+(?:sûrement|certainement))?\s+(?:monter|doubler|grimper)\b"
    r"|\bvont(?:\s+(?:sûrement|certainement))?\s+(?:monter|doubler|grimper)\b|\bpari\s+sûr\b", re.I)
NEGATION = re.compile(r"\b(?:not|no|never|nothing|nor|without|ne|pas|aucun|aucune|jamais|rien|sans)\b|n['’]|n't\b",
                      re.I)


def predictions(text: str) -> list[str]:
    """Phrases that promise or predict returns, unless negated within the few words before them."""
    found = []
    for m in PREDICTION.finditer(text):
        before = text[max(0, m.start() - 30):m.start()]
        if not NEGATION.search(before):
            found.append(m.group())
    return found


def check_answer(text: str, trace, lang: str = "en") -> dict:
    """Numbers in the answer must match evidence numbers (as written, or x100 for fractions) within their
    rounding. In a sentence tagged [fact: step N] they must come from the cited steps (or the user step,
    which holds the persona profile); elsewhere from any evidence step. Years (e.g. "2022") may come from
    anywhere in the trace. Citations must point to worker or user steps. Signs are not compared
    ("a drawdown of 63.5%" is fine). lang="fr": French number style (51,1 %) is read as 51.1 %."""
    text = normalize_numbers(text, lang)
    reasons, bad = [], []
    citable = {s["step"]: s for s in trace.steps if _evidence(s)}
    user_steps = [s for s in trace.steps if s["actor"] == "user"]
    known_all = trace_numbers(trace)
    for line in text.splitlines():
        for sentence in SENTENCE.split(line):
            refs = [int(n) for r in STEP_REF.findall(sentence) for n in re.findall(r"\d+", r)]
            for n in refs:
                if n not in citable:
                    reasons.append(f"citation step {n} is not a worker or user step")
            body = STEP_REF.sub(" ", sentence)
            cited = [citable[n] for n in refs if n in citable]
            known = trace_numbers(trace, user_steps + cited) if cited else known_all
            for b in _unsupported(body, known):
                if not (YEAR.match(b) and not _unsupported(b, known_all)):  # a year anywhere in the trace is fine
                    bad.append(b)
    if bad:
        reasons.append(f"numbers not found in the cited steps / trace: {sorted(set(bad))}")
    sure = predictions(STEP_REF.sub(" ", text))
    if sure:
        reasons.append(f"the answer promises or predicts returns {sorted(set(sure))}; describe historical numbers "
                       "and risks instead, never certainty about the future")
    return _verdict(list(dict.fromkeys(reasons)))
