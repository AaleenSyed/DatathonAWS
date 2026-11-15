"""Build the ExplainerPayload (contracts/openapi.yaml) from one pipeline run. Deterministic, no LLM.

Every number in the payload is copied from a worker step of the run trace and carries that step's number
(`traceSteps` / `traceStep`), so the UI can show where it came from.
"""
import math
import re

import reviewer
from personas import PERSONAS
from workers import data_retriever as dr
from workers import risk_analyst as ra

CAVEATS = ["simulation_only", "past_performance", "survivorship_bias", "fred_revised_vintages",
           "macro_publication_lag", "equal_weight_baskets"]
MAX_LIMITATIONS = 15
TAG = re.compile(r"\[\s*(fact|assumption|scenario)\b[^\]]*\]", re.I)
STEP_NUMS = re.compile(r"(\d+)\s*[-–]\s*(\d+)|(\d+)")
MAX_RANGE = 40  # "[fact: step 17-24]" expands to 17..24; longer ranges are taken as two steps
MARKDOWN = re.compile(r"(\*\*|__|`)")
LEADER = re.compile(r"^\s*(?:[-*+>]|\d+\.)\s+|^\s*#+\s*")


def _norm(s) -> str:
    return str(s or "").strip().lower()


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _target_of(step):
    i = step.get("input") or {}
    t = (i.get("ticker") or i.get("sector") or i.get("target") or i.get("tickers_or_sector")
         or i.get("sector_or_ticker") or i.get("tickers"))
    return " ".join(sorted(t)) if isinstance(t, (list, tuple)) else t


class Run:
    """Lookups over the worker steps of one trace."""

    def __init__(self, trace):
        self.trace = trace
        self.workers = [s for s in trace.steps if s["actor"].startswith("worker:")]
        self.ok = [s for s in self.workers if isinstance(s["output"], dict) and s["output"].get("status") == "ok"]
        universe = dr.get_universe().get("data", [])
        self.assets = {r["ticker"]: r for r in universe}

    def steps(self, action, target=None):
        return [s for s in self.ok if s["action"] == action
                and (target is None or _norm(_target_of(s)) == _norm(target))]

    def latest(self, action, target=None):
        found = self.steps(action, target)
        return found[-1] if found else None

    def suitability(self, target, prefer_weighted: bool):
        checks = self.steps("check_suitability", target)
        weighted = [s for s in checks if (s["input"] or {}).get("proposed_weight") is not None]
        unweighted = [s for s in checks if s not in weighted]
        first, second = (weighted, unweighted) if prefer_weighted else (unweighted, weighted)
        return (first or second or [None])[-1]

    def resolve(self, name):
        """(kind, members) for a ticker or sector group; (None, []) when unknown."""
        if name in self.assets:
            return "asset", [self.assets[name]]
        members = ra.sector_members(name)
        return (ra.group_kind(members), members) if members else (None, [])


def _member(r) -> dict:
    return {"ticker": r["ticker"], "name": r["name"], "assetClass": r["asset_class"]}


def _range(d) -> dict:
    keys = {"annualized_vol": "annualizedVol", "max_drawdown": "maxDrawdown", "total_return": "totalReturn"}
    return {camel: {"min": d[k]["min"], "minTicker": d[k]["min_ticker"], "max": d[k]["max"],
                     "maxTicker": d[k]["max_ticker"]} for k, camel in keys.items()}


def target_summary(run: Run, name: str, prefer_weighted: bool) -> dict | None:
    kind, members = run.resolve(name)
    if kind is None:
        return None
    out = {"name": name, "kind": kind, "members": [_member(m) for m in members], "riskLabel": None,
           "annualizedVol": None, "maxDrawdown": None, "totalReturn": None, "range": None,
           "suitabilityOverall": None, "momentum12m": None, "trend": None, "period": None, "currency": None,
           "traceSteps": []}
    risk = run.latest("analyze_asset" if kind == "asset" else "analyze_sector", name)
    if risk:
        d, o = risk["output"]["data"], risk["output"]
        out.update(period=o.get("period"), currency=o.get("currency"))
        if kind == "building_block":
            out["range"] = _range(d["range"])
        else:
            out.update(riskLabel=d.get("risk_label"), annualizedVol=_num(d.get("annualized_vol")),
                       maxDrawdown=_num(d.get("max_drawdown")), totalReturn=_num(d.get("total_return")))
        out["traceSteps"].append(risk["step"])
    mom = run.latest("sector_momentum", name)
    if mom:
        d = mom["output"]["data"]
        entry = d.get("basket") if kind == "industry" else (d.get("members") or {}).get(name) if kind == "asset" else None
        if entry:
            out.update(momentum12m=_num(entry.get("momentum_12m")), trend=entry.get("trend"))
            out["traceSteps"].append(mom["step"])
    suit = run.suitability(name, prefer_weighted)
    if suit:
        out["suitabilityOverall"] = suit["output"]["data"]["overall"]
        out["traceSteps"].append(suit["step"])
    return out


def risk_rows(run: Run, name: str) -> list[dict]:
    """Chart rows for one target: one row for an asset or industry basket, one per member for a building block."""
    kind, _ = run.resolve(name)
    if kind is None:
        return []
    risk = run.latest("analyze_asset" if kind == "asset" else "analyze_sector", name)
    stress = run.latest("stress_test_2022", name)
    stress_data = stress["output"]["data"] if stress else {}
    if not risk:
        return []
    d = risk["output"]["data"]
    metrics = d.get("member_metrics", {}) if kind == "building_block" else {name: d}
    rows = []
    for row_name, m in metrics.items():
        s = stress_data.get(row_name) or {}
        steps = [risk["step"]] + ([stress["step"]] if s else [])
        rows.append({"name": row_name, "group": name, "kind": kind, "annualizedVol": _num(m.get("annualized_vol")),
                     "maxDrawdown": _num(m.get("max_drawdown")), "totalReturn": _num(m.get("total_return")),
                     "riskLabel": m.get("risk_label"), "stress2022Return": _num(s.get("total_return")),
                     "stress2022MaxDrawdown": _num(s.get("max_drawdown")), "traceSteps": steps})
    return rows


def suitability_results(run: Run) -> list[dict]:
    latest = {}
    for s in run.steps("check_suitability"):
        d = s["output"]["data"]
        latest[(_norm(d["target"]), d.get("proposed_weight"))] = s  # later checks replace earlier ones
    out = []
    for s in sorted(latest.values(), key=lambda s: s["step"]):
        d = s["output"]["data"]
        out.append({"target": d["target"], "targetKind": d["target_kind"], "proposedWeight": _num(d.get("proposed_weight")),
                    "overall": d["overall"], "traceStep": s["step"],
                    "checks": [{"rule": c["rule"], "status": c["status"], "limit": c.get("limit"),
                                "value": c.get("value"), "explanation": c.get("explanation", "")}
                               for c in d["checks"]]})
    return out


def market_context(run: Run, as_of: str) -> dict | None:
    cycle, mood = run.latest("cycle_phase"), run.latest("fear_hope")
    if not cycle and not mood:
        return None
    c = cycle["output"]["data"] if cycle else {}
    f = mood["output"]["data"] if mood else {}
    return {"asOf": c.get("as_of") or f.get("as_of") or as_of, "phase": c.get("phase"),
            "ruleFired": c.get("rule_fired"), "sectorTilt": list(c.get("sector_tilt") or []),
            "vix": _num((f.get("vix") or {}).get("value")), "mood": f.get("mood"),
            "creditSpreadRising": (f.get("credit_spread") or {}).get("rising_stress"),
            "consumerSentiment": _num((f.get("consumer_sentiment") or {}).get("value")),
            "traceSteps": [s["step"] for s in (cycle, mood) if s]}


def cited_steps(sentence: str) -> list[int]:
    nums = []
    for ref in reviewer.STEP_REF.findall(sentence):
        for a, b, single in STEP_NUMS.findall(ref):
            if single:
                nums.append(int(single))
            elif 0 <= int(b) - int(a) <= MAX_RANGE:
                nums.extend(range(int(a), int(b) + 1))
            else:
                nums.extend([int(a), int(b)])
    return list(dict.fromkeys(nums))


def _source_of(step) -> str | None:
    if step["actor"] == "user":
        return "persona profile (personas.py; numeric limits are team assumptions)"
    o = step["output"] if isinstance(step["output"], dict) else {}
    if not o.get("source"):
        return None
    period = o.get("period") or {}
    parts = [str(o["source"])]
    if period.get("start") and period.get("end"):
        parts.append(f"{period['start']} to {period['end']}")
    if o.get("currency"):
        parts.append(str(o["currency"]))
    return "; ".join(parts)


def claims(answer: str, trace) -> list[dict]:
    """Tagged sentences of the answer. A sentence with [assumption] or [scenario] keeps that kind even when it
    also cites facts (e.g. a historical tendency based on the cycle signals)."""
    by_step = {s["step"]: s for s in trace.steps}
    out = []
    for line in answer.splitlines():
        for sentence in reviewer.SENTENCE.split(line.strip()):
            kinds = {k.lower() for k in TAG.findall(sentence)}
            if not kinds:
                continue
            kind = "scenario" if "scenario" in kinds else "assumption" if "assumption" in kinds else "fact"
            steps = [n for n in cited_steps(sentence) if n in by_step]
            body = LEADER.sub("", MARKDOWN.sub("", TAG.sub("", sentence)))
            body = re.sub(r"\s+([.,;:!?])", r"\1", " ".join(body.split())).strip()
            if not body:
                continue
            sources = list(dict.fromkeys(src for n in steps if (src := _source_of(by_step[n]))))
            out.append({"text": body, "kind": kind, "traceSteps": steps, "sources": sources})
    return out


def limitations(run: Run) -> list[str]:
    seen = []
    for s in run.ok:
        for w in s["output"].get("warnings") or []:
            if w not in seen:
                seen.append(str(w))
    return seen[:MAX_LIMITATIONS]


def _verdict(v) -> dict:
    v = v or {}
    return {"verdict": "pass" if v.get("verdict") == "pass" else "fail",
            "reasons": [str(r) for r in v.get("reasons") or []]}


def build(result: dict, persona_key: str, lang: str) -> dict:
    """result = ChatSession.ask(...) output."""
    trace, plan = result["trace"], result.get("plan") or {}
    run = Run(trace)
    persona = PERSONAS[persona_key]
    question = trace.meta.get("question", "")
    requested = [t for t in list(plan.get("requested_targets") or []) + reviewer.extract_targets(question)
                 if run.resolve(t)[0]]
    requested = list(dict.fromkeys(requested))
    recommended = [t for t in dict.fromkeys(plan.get("recommended_sectors") or []) if run.resolve(t)[0]]
    rows, seen = [], set()
    for name in requested + recommended:
        for row in risk_rows(run, name):
            if (row["name"], row["group"]) not in seen:
                seen.add((row["name"], row["group"]))
                rows.append(row)
    actions = [s["action"] for s in trace.steps]
    work, answer = _verdict(result.get("work_verdict")), _verdict(result.get("answer_verdict"))
    saved = result.get("saved") or {}
    return {
        "language": lang,
        "persona": {"id": persona_key, "name": persona["name"]},
        "recommendedSectors": [s for t in recommended if (s := target_summary(run, t, prefer_weighted=False))],
        "requestedTargets": [s for t in requested if (s := target_summary(run, t, prefer_weighted=True))],
        "conflicts": [str(c) for c in plan.get("conflicts_found") or []],
        "suitability": suitability_results(run),
        "riskTable": rows,
        "personaLimits": persona["limits"],
        "marketContext": market_context(run, trace.meta.get("analysis_date", "")),
        "claims": claims(result.get("answer", ""), trace),
        "review": {"work": work, "answer": answer,
                   "workRetries": max(0, actions.count("review_work") - 1),
                   "answerRetries": max(0, actions.count("write_answer") - 1),
                   # a guardrail block ("blocked") is reported as fail but is not an incomplete analysis
                   "incomplete": (result.get("work_verdict") or {}).get("verdict") == "fail"},
        "limitations": limitations(run),
        "caveats": list(CAVEATS),
        "run": {"runId": trace.run_id, "sessionId": trace.meta.get("session_id"),
                "analysisDate": trace.meta.get("analysis_date"), "s3Uri": saved.get("s3")},
    }
