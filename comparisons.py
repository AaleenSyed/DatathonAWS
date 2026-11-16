"""Comparison facts: ranks and comparison sentences computed in Python from the worker steps of a run trace.

The presenter (an LLM) must never compare or rank numbers itself (the eval found "17.0% vol lower than 15.7%").
build(trace, plan) reads the latest successful risk / 2022 stress / momentum step of every target and returns,
per metric:
  rankings  every sector group (industry basket) ranked, and the individual assets ranked, with a ready-made
            sentence: "Utilities has the lowest annualized volatility (14.7%), Financials 2nd (15.7%), ..."
  pairs     each requested target vs each recommended sector group:
            "NVDA has a higher annualized volatility (51.1%) than Consumer Staples (17.0%)."
Values are ranked as shown (percent, one decimal), so two values that print the same are tied. Building blocks
(Bonds, Broad market, ...) have no blended figure: their members are ranked with the assets. No new data:
every value is copied from the step listed next to it. Deterministic, no LLM, never raises.
"""
import math

from workers import data_retriever as dr

DEFAULT_START = "2021-11-12"  # starter dataset window (CLAUDE.md)

# key, label, best value first ("low": lowest first; "shallow": drawdown closest to zero first; "high")
METRICS = [
    ("annualized_vol", "annualized volatility", "low"),
    ("max_drawdown", "maximum drawdown", "shallow"),
    ("total_return", "total return", "high"),
    ("return_2022", "2022 return", "high"),
    ("max_drawdown_2022", "2022 maximum drawdown", "shallow"),
    ("momentum_6m", "6-month momentum", "high"),
    ("momentum_12m", "12-month momentum", "high"),
]
# words for the first / last of a ranking
WORDS = {"low": ("lowest", "highest"), "high": ("highest", "lowest"), "shallow": ("smallest", "deepest")}
NOTE = ("Ranks and comparisons computed in Python from the cited worker steps. Use these sentences as they are "
        "(order, ranks and values); never compare or rank numbers yourself.")


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _shown(x: float) -> float:
    """The value as the answer prints it (percent, one decimal): ranking uses it, so ties are what users see."""
    return round(x * 100, 1)


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _target(step):
    i = step.get("input") or {}
    return i.get("ticker") or i.get("sector") or i.get("tickers_or_sector") or i.get("sector_or_ticker")


def _latest(trace) -> dict:
    """{(action, target): step} for the latest successful worker step of each action and target."""
    out = {}
    for s in trace.steps:
        o = s["output"] if isinstance(s["output"], dict) else {}
        if s["actor"].startswith("worker:") and o.get("status") == "ok" and isinstance(_target(s), str):
            out[(s["action"], _target(s))] = s
    return out


RISK_KEYS = ("annualized_vol", "max_drawdown", "total_return")


def collect(trace) -> tuple[dict, dict, dict]:
    """(sectors, assets, origin). sectors / assets = {name: {metric: (value, step)}} for industry baskets and
    for single assets; origin = {ticker: "direct" | "block" | "industry"} (analyzed on its own, member of a
    building block, member of an industry basket). A directly analyzed ticker keeps its own step."""
    sectors, assets, origin = {}, {}, {}
    latest = _latest(trace)

    def put(table, name, metric, value, step):
        v = _num(value)
        if v is not None:
            table.setdefault(name, {})[metric] = (v, step)

    for kind in ("industry", "building_block", "direct"):  # later passes win: direct analysis last
        for (action, target), s in latest.items():
            d = s["output"].get("data") or {}
            if action == "analyze_sector" and d.get("kind") == kind:
                if kind == "industry":
                    for k in RISK_KEYS:
                        put(sectors, target, k, d.get(k), s["step"])
                for name, m in (d.get("member_metrics") or {}).items():
                    origin[name] = "industry" if kind == "industry" else "block"
                    for k in RISK_KEYS:
                        put(assets, name, k, m.get(k), s["step"])
            elif action == "analyze_asset" and kind == "direct":
                name = d.get("ticker") or target
                origin[name] = "direct"
                for k in RISK_KEYS:
                    put(assets, name, k, d.get(k), s["step"])
    for (action, target), s in latest.items():
        d = s["output"].get("data") or {}
        if action == "stress_test_2022":
            for name, m in d.items():
                table = sectors if name in sectors else assets if name in assets else None
                if isinstance(m, dict) and table is not None:
                    put(table, name, "return_2022", m.get("total_return"), s["step"])
                    put(table, name, "max_drawdown_2022", m.get("max_drawdown"), s["step"])
        elif action == "sector_momentum":
            rows = [(assets, n, m) for n, m in (d.get("members") or {}).items() if n in assets]
            if d.get("kind") == "industry" and target in sectors and d.get("basket"):
                rows.append((sectors, target, d["basket"]))
            for table, name, m in rows:
                for k in ("momentum_6m", "momentum_12m"):
                    put(table, name, k, m.get(k), s["step"])
    return sectors, assets, origin


def _ordered(table: dict, metric: str, best: str) -> list[dict]:
    rows = [{"name": n, "value": m[metric][0], "shown": pct(m[metric][0]), "step": m[metric][1]}
            for n, m in table.items() if metric in m]
    # best first: low -> ascending; high -> descending; shallow drawdown (closest to zero) -> descending
    rows.sort(key=lambda r: (_shown(r["value"]) * (1 if best == "low" else -1), r["name"]))
    rank = 0
    for i, r in enumerate(rows):  # competition ranking on the shown value: 15.7%, 15.7%, 17.0% -> 1, 1, 3
        if i == 0 or _shown(r["value"]) != _shown(rows[i - 1]["value"]):
            rank = i + 1
        r["rank"] = rank
    return rows


def ranking_sentence(rows: list[dict], label: str, best: str, among: str) -> str:
    first_w, last_w = WORDS[best]
    n_first = sum(r["rank"] == 1 for r in rows)
    lead = rows[:n_first]
    names = " and ".join(r["name"] for r in lead)
    if n_first == len(rows):
        return f"{names} have the same {label} ({lead[0]['shown']}) {among}."
    verb = "are tied for" if n_first > 1 else "has"
    parts = [f"{names} {verb} the {first_w} {label} {among} ({lead[0]['shown']})"]
    last_rank = rows[-1]["rank"]
    i = n_first
    while i < len(rows):
        same = [r for r in rows[i:] if r["rank"] == rows[i]["rank"]]
        who = " and ".join(r["name"] for r in same)
        if rows[i]["rank"] == last_rank:
            word = f"tied for the {last_w}" if len(same) > 1 else f"the {last_w}"
        else:
            word = ("tied " if len(same) > 1 else "") + ordinal(rows[i]["rank"])
        parts.append(f"{who} {word} ({same[0]['shown']})")
        i += len(same)
    return ", ".join(parts) + "."


def pair_sentence(a: dict, b: dict, label: str, best: str) -> str:
    if _shown(a["value"]) == _shown(b["value"]):
        return f"{a['name']} and {b['name']} have the same {label} ({a['shown']})."
    if best == "shallow":  # drawdowns: closer to zero = shallower
        word = "deeper" if abs(a["value"]) > abs(b["value"]) else "shallower"
    else:
        word = "higher" if a["value"] > b["value"] else "lower"
    return f"{a['name']} has a {word} {label} ({a['shown']}) than {b['name']} ({b['shown']})."


def _plan_names(plan: dict) -> tuple[list[str], list[str]]:
    plan = plan or {}
    return ([t for t in plan.get("requested_targets") or [] if t],
            [t for t in plan.get("recommended_sectors") or [] if t])


def _members(name: str) -> list[str]:
    rows = dr.get_universe().get("data", [])
    if any(r["ticker"] == name for r in rows):
        return [name]
    return [r["ticker"] for r in rows if r["sector"] == name or r["sector"].split(" (")[0] == name]


def build(trace, plan: dict | None = None, as_of: str | None = None, window_start: str | None = None) -> dict:
    """Worker-style result with the comparison facts. Assets ranked: tickers analyzed on their own, plus the
    members of the groups the plan names (requested or recommended); with no group named, all building-block
    members. Industry baskets: every one analyzed (rank_sectors_for_persona analyzes them all)."""
    try:
        requested, recommended = _plan_names(plan)
        sectors, assets, origin = collect(trace)
        named = {m for t in requested + recommended for m in _members(t)}
        keep = {n for n, o in origin.items() if o == "direct" or n in named or (not named and o == "block")}
        assets = {n: m for n, m in assets.items() if n in keep}
        rankings, pairs, steps = [], [], set()
        for key, label, best in METRICS:
            for kind, table, among in (("sector groups", sectors, "among the sector groups analyzed"),
                                       ("assets", assets, "among the assets analyzed")):
                rows = _ordered(table, key, best)
                if len(rows) < 2:
                    continue
                steps |= {r["step"] for r in rows}
                rankings.append({"metric": label, "among": kind,
                                 "order": [{"rank": r["rank"], "name": r["name"], "value": r["shown"]} for r in rows],
                                 "sentence": ranking_sentence(rows, label, best, among),
                                 "steps": sorted({r["step"] for r in rows})})
            for a_name in requested:
                for b_name in recommended:
                    a = (sectors.get(a_name) or assets.get(a_name) or {}).get(key)
                    b = (sectors.get(b_name) or assets.get(b_name) or {}).get(key)
                    if a_name == b_name or not a or not b:
                        continue
                    ra = {"name": a_name, "value": a[0], "shown": pct(a[0])}
                    rb = {"name": b_name, "value": b[0], "shown": pct(b[0])}
                    steps |= {a[1], b[1]}
                    pairs.append({"metric": label, "sentence": pair_sentence(ra, rb, label, best),
                                  "steps": sorted({a[1], b[1]})})
        period = {"start": window_start or DEFAULT_START, "end": as_of or trace.meta.get("analysis_date")}
        return {"status": "ok", "data": {"note": NOTE, "rankings": rankings, "pairs": pairs},
                "source": "computed in Python from the worker steps listed in each fact; no new data",
                "period": period, "currency": "CAD", "warnings": []}
    except Exception as e:
        return {"status": "error", "error": f"comparisons failed: {e}"}
