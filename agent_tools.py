"""Worker functions wrapped as Strands @tool for the boss agent.

Only summary workers are exposed (no raw price series: too many tokens). Persona, analysis window and
analysis date are fixed by the session in CONTEXT, not chosen by the LLM, so the boss cannot change the
persona's limits or look past the analysis date. Every call is recorded in the current RunTrace and the
result carries its `trace_step` number. Tools never raise.
"""
from strands import tool

from workers import data_retriever as dr
from workers import market_context as mc
from workers import risk_analyst as ra
from workers import suitability as su

WINDOW_START = "2021-11-12"  # starter dataset window (CLAUDE.md)
CONTEXT = {"trace": None, "persona": None, "as_of": "2026-11-12"}


def _run(worker: str, action: str, fn, **kwargs) -> dict:
    try:
        out = fn(**kwargs)
    except Exception as e:  # workers should not raise; belt and braces
        out = {"status": "error", "error": f"{action} raised: {e}"}
    t = CONTEXT["trace"]
    step = t.add(f"worker:{worker}", action, kwargs, out) if t else None
    return {**out, "trace_step": step}


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


TOOLS = [list_sectors, analyze_asset, analyze_sector, stress_test_2022, correlation, cycle_phase, fear_hope,
         sector_momentum, check_suitability]
