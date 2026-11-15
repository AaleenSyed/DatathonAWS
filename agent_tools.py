"""Worker functions wrapped as Strands @tool for the boss agent.

Only summary workers are exposed (no raw price series: too many tokens). Persona, analysis window and
analysis date are fixed by the session in CONTEXT, not chosen by the LLM, so the boss cannot change the
persona's limits or look past the analysis date. Every worker call is recorded in the current RunTrace with
its FULL output (the presenter, explainer and UI read that); the boss only gets a COMPACT summary (key numbers
as percent strings, risk label, overall status, warning count) with the `trace_step` number. Tools never raise.

Coarse tools (fewer boss turns): assess_target = risk + 2022 stress + suitability for one target;
rank_sectors_for_persona = suitability + key risk for every industry and the bonds / broad-market groups,
ranked; market_snapshot = cycle phase + mood. Every inner worker call still gets its own trace step.
"""
import copy
import json
import os
import threading
import time

from strands import tool

from personas import PERSONAS

from workers import data_retriever as dr
from workers import market_context as mc
from workers import risk_analyst as ra
from workers import suitability as su

WINDOW_START = "2021-11-12"  # starter dataset window (CLAUDE.md)
CONTEXT = {"trace": None, "persona": None, "as_of": "2026-11-12"}


# ---------- compact results for the boss ----------

def _p(x):
    """0.5113 -> "51.1%" (what the boss reads; the trace keeps the raw fraction)."""
    return f"{x:.1%}" if isinstance(x, (int, float)) and not isinstance(x, bool) else x


def _metrics(d: dict) -> dict:
    out = {"risk_label": d.get("risk_label"), "annualized_vol": _p(d.get("annualized_vol")),
           "max_drawdown": _p(d.get("max_drawdown")), "total_return": _p(d.get("total_return"))}
    return {k: v for k, v in out.items() if v is not None}


def _range(d: dict) -> dict:
    return {k: f"{_p(r['min'])} ({r['min_ticker']}) to {_p(r['max'])} ({r['max_ticker']})"
            for k, r in (d.get("range") or {}).items()}


def _rule_value(v):
    if isinstance(v, dict):
        return {k: _p(x) for k, x in v.items()}
    return _p(v) if not isinstance(v, list) else v


def compact(action: str, out: dict) -> dict:
    """Short version of a worker result for the LLM. Errors pass through unchanged."""
    if not isinstance(out, dict) or out.get("status") != "ok":
        return out
    d = out.get("data") or {}
    if action == "list_sectors":
        data = {g: {"kind": v["kind"], "members": [m["ticker"] for m in v["members"]]} for g, v in d.items()}
    elif action == "analyze_asset":
        data = {"ticker": d.get("ticker"), "sector": d.get("sector"), **_metrics(d)}
    elif action == "analyze_sector":
        data = {"sector": d.get("sector"), "kind": d.get("kind"), "members": d.get("members")}
        data.update(_range(d) if d.get("kind") == "building_block" else _metrics(d))
    elif action == "stress_test_2022":
        data = {n: {"return_2022": _p(m.get("total_return")), "max_drawdown_2022": _p(m.get("max_drawdown"))}
                for n, m in d.items()}
    elif action == "sector_momentum":
        rows = {"basket": d["basket"]} if d.get("basket") else d.get("members") or {}
        data = {n: {"momentum_12m": _p(m.get("momentum_12m")), "trend": m.get("trend")} for n, m in rows.items()}
    elif action == "check_suitability":
        data = {"target": d.get("target"), "proposed_weight": _p(d.get("proposed_weight")), "overall": d.get("overall"),
                "not_pass": [{"rule": c["rule"], "status": c["status"], "value": _rule_value(c.get("value")),
                              "limit": _rule_value(c.get("limit"))}
                             for c in d.get("checks", []) if c["status"] not in ("pass", "not_applicable")]}
    elif action == "cycle_phase":
        data = {k: d.get(k) for k in ("phase", "sector_tilt", "rule_fired")}
    elif action == "fear_hope":
        data = {"mood": d.get("mood"), "vix": (d.get("vix") or {}).get("value"),
                "credit_spread_rising": (d.get("credit_spread") or {}).get("rising_stress"),
                "consumer_sentiment": (d.get("consumer_sentiment") or {}).get("value")}
    else:
        data = d
    return {"status": "ok", "data": data, "warnings": len(out.get("warnings") or [])}


# Worker results depend only on their inputs and the data files, which do not change while the process runs,
# so successful results are cached per process (TOOL_CACHE=0 turns it off). A cached result is still recorded
# as its own trace step, with the same input and output as a fresh call; the step is marked "cached".
_CACHE: dict[str, dict] = {}
_CACHE_LOCK = threading.Lock()


def _cache_on() -> bool:
    return os.getenv("TOOL_CACHE", "1") != "0"


def clear_cache():
    with _CACHE_LOCK:
        _CACHE.clear()


def _record(worker: str, action: str, fn, **kwargs) -> tuple[dict, int | None]:
    """Run a worker and record its FULL output as a trace step. Returns (full output, step number)."""
    t0 = time.perf_counter()
    key = f"{action}|{json.dumps(kwargs, sort_keys=True, default=str)}" if _cache_on() else None
    with _CACHE_LOCK:
        hit = copy.deepcopy(_CACHE[key]) if key in _CACHE else None
    if hit is not None:
        out = hit
    else:
        try:
            out = fn(**kwargs)
        except Exception as e:  # workers should not raise; belt and braces
            out = {"status": "error", "error": f"{action} raised: {e}"}
        if key and isinstance(out, dict) and out.get("status") == "ok":
            with _CACHE_LOCK:
                _CACHE[key] = copy.deepcopy(out)
    t = CONTEXT["trace"]
    step = t.add(f"worker:{worker}", action, kwargs, out, duration_ms=(time.perf_counter() - t0) * 1000) if t else None
    if t and hit is not None:
        t.steps[step - 1]["cached"] = True
    return out, step


def _run(worker: str, action: str, fn, **kwargs) -> dict:
    """Run + record; the boss gets the compact result with its trace_step."""
    out, step = _record(worker, action, fn, **kwargs)
    return {**compact(action, out), "trace_step": step}


def _groups() -> dict:
    groups = {}
    for r in dr.get_universe().get("data", []):
        g = groups.setdefault(r["sector"].split(" (")[0], {"members": [], "labels": set()})
        g["members"].append({"ticker": r["ticker"], "name": r["name"], "asset_class": r["asset_class"]})
        g["labels"].add(r["sector"])
    for name, g in groups.items():
        g["kind"] = ra.group_kind([{"asset_class": m["asset_class"]} for m in g["members"]])
        g["labels"] = sorted(g["labels"])
    return groups


def groups_text() -> str:
    """One line per sector group for the boss prompt: name (kind): tickers."""
    return "\n".join(f"- {g} ({v['kind']}): {', '.join(m['ticker'] for m in v['members'])}"
                     for g, v in _groups().items())


@tool
def list_sectors() -> dict:
    """List the sector groups of the analysis universe with their kind and member assets.

    kind "industry" = all-equity group (what the chatbot recommends); kind "building_block" = ETFs or crypto
    (bonds, broad market, gold, crypto) that are paired with an industry. Call this first to pick valid names.
    """
    def f():
        return {"status": "ok", "data": _groups(), "source": "assets_universe.csv (organizers' sector labels)",
                "period": None, "currency": None, "warnings": []}
    return _run("data_retriever", "list_sectors", f)


@tool
def analyze_asset(ticker: str) -> dict:
    """Risk metrics for one asset over the full analysis window, in CAD: total and annualized return,
    annualized volatility, max and current drawdown, risk label (and USD volatility for USD assets).

    Args:
        ticker: a ticker from the universe, e.g. "NVDA", "XBB.TO", "BTC-USD"
    """
    return _run("risk_analyst", "analyze_asset", ra.analyze_asset,
                ticker=ticker, start=WINDOW_START, end=CONTEXT["as_of"])


@tool
def analyze_sector(sector: str) -> dict:
    """Risk metrics for a sector group over the full analysis window, in CAD. Industry = equal-weight basket +
    per-member metrics; building block = per-member metrics and min-max range (no blended figure).

    Args:
        sector: a group name from list_sectors, e.g. "Utilities", "Bonds", "Information Technology"
    """
    return _run("risk_analyst", "analyze_sector", ra.analyze_sector,
                sector=sector, start=WINDOW_START, end=CONTEXT["as_of"])


@tool
def stress_test_2022(target: str) -> dict:
    """Total return and max drawdown in calendar 2022 (rate-shock year) for a ticker or a sector group.

    Args:
        target: a ticker or sector group name
    """
    if CONTEXT["as_of"] < ra.STRESS_END:
        return _run("risk_analyst", "stress_test_2022", lambda **k: {
            "status": "error", "error": f"analysis date {CONTEXT['as_of']} is before the end of 2022"},
            tickers_or_sector=target)
    return _run("risk_analyst", "stress_test_2022", ra.stress_test_2022, tickers_or_sector=target)


@tool
def correlation(tickers: list[str]) -> dict:
    """Correlation of daily returns between 2 or more tickers over the analysis window.

    Args:
        tickers: list of tickers from the universe
    """
    return _run("risk_analyst", "correlation", ra.correlation,
                tickers=tickers, start=WINDOW_START, end=CONTEXT["as_of"])


@tool
def cycle_phase() -> dict:
    """Business-cycle phase on the analysis date from FRED rules (recession risk / early / mid / late cycle),
    with the signal values and the sectors that have historically tended to do well in that phase."""
    return _run("market_context", "cycle_phase", mc.cycle_phase, as_of=CONTEXT["as_of"])


@tool
def fear_hope() -> dict:
    """Market mood on the analysis date: VIX level (calm / normal / fear), credit-spread trend, consumer sentiment."""
    return _run("market_context", "fear_hope", mc.fear_hope, as_of=CONTEXT["as_of"])


@tool
def sector_momentum(target: str) -> dict:
    """6- and 12-month momentum, 12-month relative strength vs XIU.TO / SPY, trend vs 200-day average and
    drawdown from 12-month high, for a ticker or sector group on the analysis date.

    Args:
        target: a ticker or sector group name
    """
    return _run("market_context", "sector_momentum", mc.sector_momentum, sector_or_ticker=target,
                as_of=CONTEXT["as_of"])


@tool
def check_suitability(target: str, proposed_weight: float | None = None) -> dict:
    """Check a ticker or sector group against the active persona's limits (crypto, single stock, sector cap,
    volatility, bonds minimum, 2022 drawdown, ESG review). Returns pass / info / flag / conflict per rule.

    Args:
        target: a ticker or sector group name
        proposed_weight: optional share of the portfolio the user wants in it, as a fraction (0.5 = 50%)
    """
    return _run("suitability", "check_suitability", su.check, persona=CONTEXT["persona"], target=target,
                proposed_weight=proposed_weight, start=WINDOW_START, end=CONTEXT["as_of"])


# ---------- coarse tools ----------

STATUS_RANK = {"pass": 0, "flag": 1, "incomplete": 2}
BUILDING_BLOCKS = ["Bonds", "Broad market"]  # what an industry can be paired with
TOP_INDUSTRIES = 4


def _is_ticker(target: str) -> bool:
    return any(r["ticker"] == target for r in dr.get_universe().get("data", []))


def _risk_call(target):
    if _is_ticker(target):
        return _record("risk_analyst", "analyze_asset", ra.analyze_asset, ticker=target, start=WINDOW_START,
                       end=CONTEXT["as_of"])
    return _record("risk_analyst", "analyze_sector", ra.analyze_sector, sector=target, start=WINDOW_START,
                   end=CONTEXT["as_of"])


def _stress_call(target):
    if CONTEXT["as_of"] < ra.STRESS_END:
        return _record("risk_analyst", "stress_test_2022", lambda **k: {
            "status": "error", "error": f"analysis date {CONTEXT['as_of']} is before the end of 2022"},
            tickers_or_sector=target)
    return _record("risk_analyst", "stress_test_2022", ra.stress_test_2022, tickers_or_sector=target)


def _suit_call(target, proposed_weight=None):
    return _record("suitability", "check_suitability", su.check, persona=CONTEXT["persona"], target=target,
                   proposed_weight=proposed_weight, start=WINDOW_START, end=CONTEXT["as_of"])


def _momentum_call(target):
    return _record("market_context", "sector_momentum", mc.sector_momentum, sector_or_ticker=target,
                   as_of=CONTEXT["as_of"])


@tool
def assess_target(target: str, proposed_weight: float | None = None) -> dict:
    """Everything needed for one ticker or sector group the user asks about, in one call: risk metrics
    (analyze_asset / analyze_sector), 2022 stress test and suitability for the active persona.

    Args:
        target: a ticker ("NVDA") or exact sector group name ("Crypto asset", "Information Technology")
        proposed_weight: share of the portfolio the user wants in it, as a fraction (0.5 = 50%), if stated
    """
    out = {}
    for key, (full, step) in (("risk", _risk_call(target)), ("stress_2022", _stress_call(target)),
                              ("suitability", _suit_call(target, proposed_weight))):
        action = {"risk": "analyze_asset" if _is_ticker(target) else "analyze_sector",
                  "stress_2022": "stress_test_2022", "suitability": "check_suitability"}[key]
        out[key] = {**compact(action, full), "trace_step": step}
    return {"status": "ok" if all(v.get("status") == "ok" for v in out.values()) else "partial",
            "target": target, **out}


def _breach(checks: list[dict]) -> float:
    """How far the target alone is above the persona's volatility / 2022-drawdown limits (0 when within)."""
    total = 0.0
    for c in checks:
        vals = [v for v in (c.get("value") or {}).values() if isinstance(v, (int, float))] \
            if isinstance(c.get("value"), dict) else []
        if c["rule"] == "vol_max" and vals:
            total += max(0.0, max(vals) - c["limit"])
        elif c["rule"] == "stress_2022_max_drawdown" and vals:
            total += max(0.0, c["limit"] - min(vals))
    return total


def rank_candidates(persona_key: str, rows: list[dict], tilt: list[str]) -> list[dict]:
    """Rank groups for a persona (the boss rule: overall pass > fewest flags > smallest volatility / 2022
    drawdown breach; conflicts excluded). Team tie-breakers: diversified groups (> 1 member) before
    one-asset groups, then groups in the current cycle tilt, then lower annualized volatility, then name."""
    ok = [r for r in rows if r["overall"] != "conflict"]
    return sorted(ok, key=lambda r: (STATUS_RANK.get(r["overall"], 3), r["flags"], round(r["breach"], 6),
                                     r["members"] < 2, r["group"] not in tilt,
                                     r["vol"] if r["vol"] is not None else 9.0, r["group"]))


@tool
def rank_sectors_for_persona() -> dict:
    """Rank every industry and the Bonds / Broad market building blocks for the active persona, in one call:
    suitability + key risk for each, ranked by the persona rule (pass > fewest flags > smallest volatility /
    2022-drawdown breach; never a conflict). Momentum and the 2022 stress test are added for the top
    candidates, so any of them can be recommended. Returns the ranked candidates compactly and `pair_with`,
    the building block to pair with when the persona has an asset-class or bonds minimum."""
    groups = _groups()
    names = [g for g, v in groups.items() if v["kind"] == "industry"] + [b for b in BUILDING_BLOCKS if b in groups]
    cycle = mc.cycle_phase(as_of=CONTEXT["as_of"])  # tie-breaker only; market_snapshot records the real step
    tilt = (cycle.get("data") or {}).get("sector_tilt") or [] if cycle.get("status") == "ok" else []
    rows, steps = [], []
    for g in names:
        risk, rstep = _risk_call(g)
        suit, sstep = _suit_call(g)
        steps += [rstep, sstep]
        if suit.get("status") != "ok":
            continue
        d, rd = suit["data"], (risk.get("data") or {}) if risk.get("status") == "ok" else {}
        vol = rd.get("annualized_vol")
        if vol is None and rd.get("range"):
            vol = rd["range"]["annualized_vol"]["max"]
        rows.append({"group": g, "kind": groups[g]["kind"], "members": len(groups[g]["members"]),
                     "overall": d["overall"], "flags": sum(c["status"] == "flag" for c in d["checks"]),
                     "breach": _breach(d["checks"]), "vol": vol, "max_drawdown": rd.get("max_drawdown"),
                     "risk_label": rd.get("risk_label"), "suitability_step": sstep, "risk_step": rstep,
                     "not_pass": [f"{c['rule']}: {c['status']}" for c in d["checks"]
                                  if c["status"] not in ("pass", "not_applicable")]})
    ranked = rank_candidates(CONTEXT["persona"], rows, tilt)
    industries = [r for r in ranked if r["kind"] == "industry"]
    blocks = [r for r in ranked if r["kind"] == "building_block"]
    limits = PERSONAS[CONTEXT["persona"]]["limits"]
    needs_block = any(k in limits for k in ("min_asset_classes", "bonds_min", "bonds_cash_min"))
    # Bonds counts toward a bonds minimum and adds a real asset class; Broad market only if Bonds is excluded
    pair = next((r["group"] for name in BUILDING_BLOCKS for r in blocks if r["group"] == name), None) \
        if needs_block else None
    top = industries[:TOP_INDUSTRIES] + [r for r in blocks if r["group"] == pair]
    for r in top:  # so whichever top candidate the boss picks has everything the reviewer asks for
        _, r["momentum_step"] = _momentum_call(r["group"])
        _, r["stress_step"] = _stress_call(r["group"])
    excluded = [r["group"] for r in rows if r["overall"] == "conflict"]
    summary = {"status": "ok", "data": {
        "persona": CONTEXT["persona"], "rule": "overall pass > fewest flags > smallest vol / 2022-drawdown breach; "
        "conflicts excluded; ties: diversified groups, cycle tilt, lower volatility",
        "cycle_tilt": tilt, "ranked": rows and [{k: r[k] for k in ("group", "kind", "overall", "flags", "breach", "vol",
                                                                    "max_drawdown", "risk_label", "suitability_step",
                                                                    "risk_step")} for r in ranked],
        "excluded_conflicts": excluded, "pair_with": pair, "candidates": [r["group"] for r in top]},
        "source": "suitability + risk_analyst workers (steps listed per group); persona limits are team assumptions",
        "period": {"start": WINDOW_START, "end": CONTEXT["as_of"]}, "currency": "CAD", "warnings": []}
    t = CONTEXT["trace"]
    step = t.add("worker:suitability", "rank_sectors", {"persona": CONTEXT["persona"]}, summary) if t else None
    return {"status": "ok", "trace_step": step, "pair_with": pair, "needs_building_block": needs_block,
            "excluded_conflicts": excluded,
            "candidates": [{"group": r["group"], "kind": r["kind"], "overall": r["overall"], "risk_label": r["risk_label"],
                            "annualized_vol": _p(r["vol"]), "max_drawdown": _p(r["max_drawdown"]),
                            "not_pass": r["not_pass"], "members": r["members"]} for r in top],
            "others_in_rank_order": [r["group"] for r in ranked if r not in top]}


@tool
def market_snapshot() -> dict:
    """Market context on the analysis date in one call: business-cycle phase with its historical sector tilt
    (cycle_phase) and market mood (fear_hope: VIX, credit-spread trend, consumer sentiment)."""
    return {"cycle": _run("market_context", "cycle_phase", mc.cycle_phase, as_of=CONTEXT["as_of"]),
            "mood": _run("market_context", "fear_hope", mc.fear_hope, as_of=CONTEXT["as_of"])}


def warm_up(personas=None, as_of: str | None = None):
    """Fill the cache with every persona's ranking and the market context (no trace). The server calls it at
    start-up in a background thread, so the first question does not pay for it."""
    saved = dict(CONTEXT)
    try:
        for p in personas or PERSONAS:
            CONTEXT.update(trace=None, persona=p, as_of=as_of or saved["as_of"])
            rank_sectors_for_persona()
            market_snapshot()
    finally:
        CONTEXT.update(saved)


COARSE_TOOLS = [assess_target, rank_sectors_for_persona, market_snapshot]
FINE_TOOLS = [list_sectors, analyze_asset, analyze_sector, stress_test_2022, correlation, cycle_phase, fear_hope,
              sector_momentum, check_suitability]
TOOLS = COARSE_TOOLS + FINE_TOOLS
