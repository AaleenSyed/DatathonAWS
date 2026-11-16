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
  no sentence promises or predicts returns ("guaranteed", "will go up", "safe bet", "sans risque", ...),
  comparative words match the order of the numbers they compare ("17.0% lower than 15.7%" fails), and
  suitability status words (pass / info / flag / conflict) match the trace for that target and rule.
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
# sentence split for the comparison and status checks: also after a claim tag ("... [fact: step 4] The ...")
PARTS = re.compile(r"(?<=[.!?\]])\s+(?=[A-ZÀ-ÖØ-Þ*_\-(«])")
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


# ---------- comparisons: "17.0% vol lower than 15.7%" ----------
# A comparative word next to two numbers must match their order. Kinds:
#   lt / gt          A < B / A > B ("lower than", "exceeds the 10.0% limit")
#   safer / riskier  lt / gt for risk numbers (skipped when the numbers are returns)
#   better / worse   lt / gt for risk numbers, gt / lt for returns; skipped when the metric is unclear
#   min / max        superlatives ("the lowest volatility (15.7%), Consumer Staples 2nd (17.0%)"): A <= / >= B,
#                    A = the value the superlative describes, B = the next value of the same metric
# Drawdowns and losses compare by size ("a smaller drawdown (-13.7%) than -22.2%"). The check only fires when
# the pairing is clear: two percentages (or two decimals) of the same metric, in the same clause.
_W = r"(?<![\w-])(?:{})(?![\w-])"
_ART = r"(?:les?|la|l['’])\s*"
COMPARATIVES = [
    ("min", _W.format(rf"lowest|smallest|shallowest|{_ART}plus\s+(?:faibles?|bas|basses?)|{_ART}moins\s+élevée?s?")),
    ("max", _W.format(rf"highest|largest|greatest|biggest|deepest|{_ART}plus\s+(?:élevée?s?|hauts?|hautes?)")),
    ("safest", _W.format(rf"safest|least\s+risky|{_ART}(?:plus\s+sûre?s?|moins\s+risquée?s?)")),
    ("riskiest", _W.format(rf"riskiest|most\s+risky|{_ART}plus\s+risquée?s?")),
    ("best", _W.format(rf"best|{_ART}meilleure?s?")),
    ("worst", _W.format(rf"worst|{_ART}pire")),  # not "au pire" (at the lowest point)
    ("lt", _W.format(r"lower|less|smaller|shallower|lesser|plus\s+(?:faibles?|bas|basses?)|moins\s+élevée?s?")),
    ("gt", _W.format(r"higher|greater|larger|bigger|deeper|steeper|plus\s+(?:élevée?s?|hauts?|hautes?|profonde?s?)")),
    ("safer", _W.format(r"safer|less\s+risky|plus\s+sûre?s?|moins\s+risquée?s?")),
    ("riskier", _W.format(r"riskier|more\s+risky|plus\s+risquée?s?")),
    ("better", _W.format(r"better|meilleure?s?")),
    ("worse", _W.format(r"worse|(?<!au\s)pire")),
    # verbs / prepositions: "16.1% exceeds the 10.0% limit" (never followed by "than")
    ("lt_to", _W.format(r"below|beneath|under|inférieure?s?|sous")),
    ("gt_to", _W.format(r"above|exceed(?:s|ed|ing)?|beyond|supérieure?s?|dépass(?:e|es|ent|ait|aient|ant)")),
]
THAN = re.compile(r"(?<!\w)(?:than|vs\.?|versus|compared\s+(?:to|with)|que|qu['’]|par\s+rapport\s+(?:à|au|aux))(?!\w)",
                  re.I)
RISK_WORDS = re.compile(r"volatil|drawdown|risk|risqu|baisse|loss|perte|decline|déclin|fell|fall|drop|drew|recul"
                        r"|chute|severe|sévère", re.I)
LOSS_WORDS = re.compile(r"drawdown|baisse|loss|perte|decline|déclin|fell|fall|drop|drew|recul|chute|severe|sévère"
                        r"|deeper|shallower|profonde", re.I)
RETURN_WORDS = re.compile(r"return|rendement|momentum|gain|performance|strength|growth|croissance", re.I)
METRIC_WORDS = [("vol", re.compile(r"volatil", re.I)),
                ("drawdown", re.compile(r"drawdown|baisse|decline|déclin|drew\s+down|fell|recul|chute", re.I)),
                ("return", re.compile(r"return|rendement", re.I)), ("momentum", re.compile(r"momentum", re.I))]
LIMIT_WORDS = re.compile(r"limit|cap\b|minimum|maximum|threshold|plafond|seuil", re.I)
CLAUSE_BREAK = re.compile(r"[;:—–]|,\s*(?:and|et)\b|\b(?:while|whereas|but|although|leav\w*|mais|alors\s+que"
                          r"|tandis\s+que|laiss\w*)\b", re.I)
AVERAGE = re.compile(r"average|moyenne|\b200\b", re.I)  # "above its 200-day average": not a number comparison
WINDOW = 80  # characters around a comparative word in which its two numbers must be
NEAR = 40    # for verbs and prepositions ("exceeds", "above") both numbers must be this close


def _numbers(body: str) -> list[dict]:
    """Numbers that can be compared: percentages or decimals; not years, not ordinals ("2nd"), not counts."""
    out = []
    for m in NUM.finditer(body):
        raw = m.group().replace(",", "").replace("−", "-")
        after = body[m.end():]
        if re.match(r"[A-Za-zÀ-ÿ]", after) or YEAR.match(raw.lstrip("-")):
            continue
        pct = re.match(r"\s*%", after) is not None
        if not pct and "." not in raw:
            continue
        near = body[max(0, m.start() - 25):m.start()] + " " + body[m.end():m.end() + 25]
        out.append({"value": float(raw), "pct": pct, "start": m.start(), "end": m.end(), "text": m.group(),
                    "limit": bool(LIMIT_WORDS.search(near))})
    return out


def _metric(body: str, n: dict) -> str | None:
    """The metric a number belongs to: a metric word right after it ("-1.4% return"), else the last one before."""
    after = body[n["end"]:n["end"] + 10]
    for name, rx in METRIC_WORDS:
        if rx.search(after):
            return name
    before = body[max(0, n["start"] - 60):n["start"]]
    best = max(((m.end(), name) for name, rx in METRIC_WORDS for m in rx.finditer(before)), default=None)
    return best[1] if best else None


def _in_closed_parens(body, n, pos) -> bool:
    """n sits in a parenthesis closed before pos: "fell -7.9% (maximum drawdown -24.0%), far less ..."."""
    between = body[n["end"]:pos]
    return between.count(")") > between.count("(")


def _pair(body, nums, w, kind):
    """(A, B) compared by the comparative word w, or None when the pairing is unclear."""
    near = NEAR if kind.endswith("_to") else WINDOW
    than = None if kind.endswith("_to") else THAN.search(body, w.end(), min(len(body), w.end() + WINDOW))
    if than and len([n for n in nums if w.end() <= n["start"] < than.start()]) > 1:
        than = None  # "... 15.0% limit, and leaves 0.0% in bonds vs 30.0%": not this word's "than"
    if not than and not kind.endswith("_to"):
        return None  # "from 0.6% to higher risk (16.1%)": an adjective with no "than" compares nothing here
    pivot = than.start() if than else w.start()
    start_b = than.end() if than else w.end()
    before = [n for n in nums if n["end"] <= pivot and pivot - n["end"] <= near]
    plain = [n for n in before if not _in_closed_parens(body, n, pivot)]
    a = (plain or before or [None])[-1]
    b = next((n for n in nums if n["start"] >= start_b and n["start"] - start_b <= near), None)
    if not a or not b:
        return None
    lo, hi = min(a["end"], w.start()), max(a["end"], w.start())
    if CLAUSE_BREAK.search(body[lo:hi]) or CLAUSE_BREAK.search(body[w.end():b["start"]]):
        return None  # A or B belongs to another clause
    if kind.endswith("_to") and AVERAGE.search(body[w.end():b["start"]]):
        return None
    return a, b


def _superlative_pair(body, nums, w):
    after = [n for n in nums if n["start"] >= w.end() and n["start"] - w.end() <= WINDOW and not n["limit"]]
    before = [n for n in nums if n["end"] <= w.start() and w.start() - n["end"] <= NEAR and not n["limit"]]
    # the value after the word ("the lowest volatility (15.7%)"), or right before it ("14.7 %, la plus basse")
    if before and (not after or w.start() - before[-1]["end"] <= 6):
        a = before[-1]
    elif after:
        a = after[0]
    else:
        return None
    b = next((n for n in nums if n["start"] > a["end"] and n["start"] - a["end"] <= WINDOW and not n["limit"]
              and n["pct"] == a["pct"]), None)
    if not b:
        return None
    between = body[a["end"]:b["start"]]
    if re.search(r"[;:—–/]", between) or ("(" in between and ")" not in between.split("(")[0]):
        return None  # another clause, a list ("-61.8% / -65.3%"), or an aside: "23.3 % (rendement total +177.6 %)"
    return a, b


def wrong_comparisons(text: str, lang: str = "en") -> list[str]:
    """Comparative words that contradict the order of the two numbers they compare ("17.0% lower than 15.7%").
    Sentences tagged [scenario] are skipped (hypothetical values)."""
    bad = []
    for line in normalize_numbers(text, lang).splitlines():
        for sentence in PARTS.split(line):
            if SCENARIO.search(sentence):
                continue
            body = STEP_REF.sub(lambda m: " " * len(m.group()), sentence)
            nums = _numbers(body)
            if len(nums) < 2:
                continue
            taken = []
            for kind, pattern in COMPARATIVES:
                for w in re.finditer(pattern, body, re.I):
                    if any(w.start() < e and s < w.end() for s, e in taken):
                        continue  # "the lowest" is not also "lower"; "plus élevée" inside "la plus élevée"
                    taken.append((w.start(), w.end()))
                    sup = kind in ("min", "max", "safest", "riskiest", "best", "worst")
                    pair = _superlative_pair(body, nums, w) if sup else _pair(body, nums, w, kind)
                    if not pair or pair[0]["pct"] != pair[1]["pct"]:
                        continue
                    a, b = pair
                    ma, mb = _metric(body, a), _metric(body, b)
                    if ma and mb and ma != mb:
                        continue  # "volatility 14.7% ... drawdown -24.0%": two metrics, no order to check
                    ctx = body[max(0, min(a["start"], w.start()) - 40):max(b["end"], w.end()) + 20]
                    risk, ret = bool(RISK_WORDS.search(ctx)), bool(RETURN_WORDS.search(ctx))
                    k = kind.replace("_to", "")
                    if k in ("safer", "riskier", "safest", "riskiest") and ret and not risk:
                        continue
                    if k in ("better", "worse", "best", "worst"):
                        if risk == ret:
                            continue  # metric unclear (or both): cannot tell which way is "better"
                        k = {"better": "lt", "worse": "gt", "best": "min", "worst": "max"}[k]
                        if ret:
                            k = {"lt": "gt", "gt": "lt", "min": "max", "max": "min"}[k]
                    k = {"safer": "lt", "riskier": "gt", "safest": "min", "riskiest": "max"}.get(k, k)
                    x, y = a["value"], b["value"]
                    # drawdowns / losses / negative limits (only drawdown limits are negative) compare by size
                    if LOSS_WORDS.search(ctx) or (x < 0 and y < 0 and (b["limit"] or (LOSS_WORDS.search(body)
                                                                                     and not ret))):
                        x, y = abs(x), abs(y)
                    if k in ("lt", "gt") and x == y:
                        continue  # a tie is not an order
                    if not {"lt": x < y, "gt": x > y, "min": x <= y, "max": x >= y}[k]:
                        bad.append(f"'{w.group()}' with {a['text']}{'%' if a['pct'] else ''} and "
                                   f"{b['text']}{'%' if b['pct'] else ''}")
    return list(dict.fromkeys(bad))


# ---------- suitability statuses: copied exactly from the trace ----------
STATUS_WORDS = [
    # nouns and adjectives only: not the verb ("conflicts with", "would conflict", "en conflit avec")
    ("conflict", r"(?<!would\s)(?<!could\s)(?<!will\s)(?<!may\s)(?<!to\s)conflicts?(?!\s+(?:\w+\s+)?with)"
                 r"|(?<!en\s)conflits?(?!\s+avec)"),
    ("flag", r"flag(?:s|ged)?|signalements?|signalée?s?"),
    ("info", r"info|information"),
    ("pass", r"pass(?:es|ed)?|conformes?"),
]
STATUS = [(s, re.compile(_W.format(p), re.I)) for s, p in STATUS_WORDS]
# plain-language rule names (presenter prompt, prompts/lang_fr.txt) -> rule codes
RULE_NAMES = [
    (("crypto_max",), r"crypto(?:\s+|-)(?:cap|limit|exposure)|plafond\s+(?:crypto|des\s+cryptoactifs)|no\s+crypto"),
    (("single_stock_max",), r"single(?:\s+|-)stock(?:\s+cap|\s+limit)?|plafond\s+par\s+titre"),
    (("sector_max",), r"sector\s+cap|plafond\s+sectoriel"),
    (("min_asset_classes",), r"asset\s+class(?:es)?|catégories\s+d['’]actifs"),
    (("stress_2022_max_drawdown",), r"2022\s+(?:drawdown|stress)|drawdown\s+(?:in|limit)|limite\s+de\s+baisse"
                                    r"|baisse\s+(?:maximale\s+)?en\s+2022"),
    (("vol_max",), r"volatility|volatilité"),
    (("bonds_min", "bonds_cash_min"), r"bonds?(?:\s*(?:/|and)\s*cash)?\s+minimum"
                                      r"|minimum\s+(?:de\s+[\d.,]+\s*%\s+)?(?:en|d['’])\s*obligations"),
    (("esg_review",), r"\besg\b"),
]
RULES = [(codes, re.compile(p, re.I)) for codes, p in RULE_NAMES]
STATUS_NEGATION = re.compile(r"(?:\b(?:no|not|never|without|zero|0|none|neither|nor|non|aucune?|pas|sans|ni)\b"
                             r"|\brather\s+than\b|\binstead\s+of\b|\b(?:clear|free)\s+of\b|\bplutôt\s+qu)"
                             r"[^.;:]{0,25}$", re.I)
OVERALL_BEFORE = re.compile(r"\b(?:all|every|overall|suitability|toutes?|tous|globale?|convenance)\b[^.;:,]{0,20}$",
                            re.I)
OVERALL_AFTER = re.compile(r"^\s+(?:all|every|toutes?|tous|overall)\b", re.I)
STATUS_CLAUSE = re.compile(r";|,\s*(?:and|but|et|mais)\b|\b(?:but|while|whereas|mais|alors\s+que|tandis\s+que)\b",
                           re.I)
SCENARIO = re.compile(r"\[\s*scenario\b", re.I)
ASSET_CLASS_USE = re.compile(r"\b(?:in|into|en|dans)\s+$", re.I)
NOT_STATUS = re.compile(r"flagged\s+(?:names|tickers|stocks|companies|holdings)\b", re.I)  # the ESG-review list
RULE_REACH = 45  # a rule name further than this from the status word (or in another clause) is not its rule


def _member_status(check, member):
    """Status of one member under a numeric rule ({ticker: value} vs limit), as the suitability worker decides."""
    v, limit = (check.get("value") or {}).get(member), check.get("limit")
    if not isinstance(v, (int, float)) or not isinstance(limit, (int, float)):
        return check["status"]  # e.g. an industry basket: the value is the basket's, not the member's
    within = v <= limit if check["rule"] == "vol_max" else v >= limit
    return "pass" if within else "flag"


def _add(table, name, rule, status):
    if status and status != "not_applicable":
        t = table.setdefault(name, {"*": set()})
        t["*"].add(status)
        if rule:
            t.setdefault(rule, set()).add(status)


def statuses_by_step(trace) -> dict[int, dict]:
    """{step: {target or member ticker: {rule: {status}, "*": {overall + every rule status}}}} for every
    successful check_suitability step. A member of a group gets its own pass / flag on numeric rules."""
    out = {}
    for s in _steps(trace, "check_suitability"):
        d, table = s["output"]["data"], {}
        name = d.get("target") or _target_of(s)
        _add(table, name, None, d.get("overall"))
        for c in d["checks"]:
            _add(table, name, c["rule"], c["status"])
        for m in [m for m in d.get("members") or [] if m != name]:
            for c in d["checks"]:
                st = _member_status(c, m) if isinstance(c.get("value"), dict) and len(d["members"]) > 1 else c["status"]
                _add(table, m, c["rule"], st)
        out[s["step"]] = table
    return out


def _merge(tables) -> dict:
    out = {}
    for table in tables:
        for name, rules in table.items():
            for rule, sts in rules.items():
                for st in sts:
                    _add(out, name, None if rule == "*" else rule, st)
    return out


def _allowed(table: dict, names, codes) -> set:
    rows = [table[n] for n in names if n in table]
    if codes:
        return set().union(*(r.get(c, set()) for r in rows for c in codes))
    return set().union(*(r["*"] for r in rows))


def _nearest(matches, pos):
    return min(matches, key=lambda m: min(abs(m[1] - pos), abs(m[2] - pos)), default=None)


def wrong_statuses(text: str, trace) -> list[str]:
    """Status words (pass / info / flag / conflict, and conflit / signalement / information / conforme) that
    differ from the trace, for the nearest rule name in its clause ("bonds/cash minimum: info"; with no rule
    name, or "passes all checks", any status counts). The target is the one named before the word in its clause
    (else those named after it); a sentence citing check_suitability steps is checked against those steps, or
    against any target of them when the named target is not in them. Skipped:
    a status word that is part of a name ("Information Technology"), negated ("zero flags", "rather than a
    pass"), in a [scenario] sentence, or with no cited suitability step and no target name."""
    by_step = statuses_by_step(trace)
    if not by_step:
        return []
    known = _merge(by_step.values())
    name_rx = [(n, re.compile(rf"(?<![\w.-]){re.escape(n)}(?![\w-])")) for n in known]
    bad = []
    for line in text.splitlines():
        for sentence in PARTS.split(line):
            if SCENARIO.search(sentence):
                continue
            refs = [int(n) for r in STEP_REF.findall(sentence) for n in re.findall(r"\d+", r)]
            cited = [n for n in refs if n in by_step]
            body = STEP_REF.sub(lambda m: " " * len(m.group()), sentence)
            names = [(n, m.start(), m.end()) for n, rx in name_rx for m in rx.finditer(body)]
            rules = [(codes, m.start(), m.end()) for codes, rx in RULES for m in rx.finditer(body)]
            # not "bonds minimum", not the asset class in "at least 30.0% in Bonds"
            targets = [t for t in names if not any(t[1] < e and s < t[2] for _, s, e in rules)
                       and not ASSET_CLASS_USE.search(body[:t[1]])]
            if not cited and not targets:
                continue
            bounds = [0] + [m.end() for m in STATUS_CLAUSE.finditer(body)] + [len(body)]
            for status, rx in STATUS:
                for w in rx.finditer(body):
                    if any(w.start() < e and s < w.end() for _, s, e in names) \
                            or STATUS_NEGATION.search(body[:w.start()]) or NOT_STATUS.match(body[w.start():]):
                        continue
                    lo = max(b for b in bounds if b <= w.start())
                    hi = min(b for b in bounds if b >= w.end())
                    in_clause = [t for t in targets if t[1] >= lo and t[2] <= hi]
                    # the subject before the word ("Bonds, volatility limit: flag, XBB.TO 6.6%, ..."), else every
                    # target after it in the clause ("Pass — volatility: TLT at 16.1%", "flag ... for XBB.TO/TLT")
                    subject = [t for t in in_clause if t[2] <= w.start()]
                    about = {_nearest(subject, w.start())[0]} if subject else {t[0] for t in in_clause}
                    target = _nearest(in_clause or targets, w.start())
                    overall = OVERALL_BEFORE.search(body[:w.start()]) or OVERALL_AFTER.match(body[w.end():])
                    near = [r for r in rules if r[1] >= lo and r[2] <= hi
                            and min(abs(r[1] - w.end()), abs(w.start() - r[2])) <= RULE_REACH]
                    # "volatility 14.7% vs 15.0% limit (pass), bonds minimum ... (info)": same comma segment first
                    seg_lo = max([lo] + [m.end() for m in re.finditer(r",\s", body[:w.start()])])
                    seg_hi = min([hi] + [w.end() + m.start() for m in re.finditer(r",\s", body[w.end():])])
                    if re.match(r"\**\)", body[w.end():]):  # "(... pass)": its rule is before the parenthesis
                        near = [r for r in near if r[2] <= w.start()]
                    same = [r for r in near if r[1] >= seg_lo and r[2] <= seg_hi]
                    rule = None if overall else _nearest(same or near, w.start())
                    codes = rule[0] if rule else None
                    if cited:
                        # the clause's target when the cited steps checked it; otherwise any target of the cited
                        # steps ("Info: the bonds minimum still has to be filled [fact: step 13, 25]")
                        scope = _merge(by_step[n] for n in cited)
                        who = [n for n in about if n in scope]
                        if not who:
                            scope = _merge([scope] + ([{target[0]: known[target[0]]}] if target else []))
                            who = list(scope)
                    else:
                        scope, who = known, sorted(about) or [target[0]]
                    allowed = _allowed(scope, who, codes)
                    if allowed and status not in allowed:
                        where = f"cited step {', '.join(map(str, cited))}" if cited else target[0]
                        what = f" {body[rule[1]:rule[2]]}" if rule else ""
                        bad.append(f"'{w.group()}' for {where}{what} (trace: {'/'.join(sorted(allowed))})")
    return list(dict.fromkeys(bad))


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
    wrong = wrong_comparisons(text)  # text is already in English number style
    if wrong:
        reasons.append(f"comparisons contradict the order of their numbers: {wrong}; never compare numbers "
                       "yourself, copy the sentences of the compare_metrics step")
    relabeled = wrong_statuses(text, trace)
    if relabeled:
        reasons.append(f"suitability statuses differ from the trace: {relabeled}; copy each status exactly as the "
                       "check_suitability step gives it for that target and rule")
    return _verdict(list(dict.fromkeys(reasons)))
