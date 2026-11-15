"""risk_analyst worker: per-asset and per-sector return, volatility, drawdown, correlation, 2022 stress test,
risk labels. Deterministic, no LLM. Prices come only from workers.data_retriever.

Groups (from the `sector` column of assets_universe.csv; exact label, or text before " ("):
- industry       = all members have asset_class "equity" -> equal-weight basket, one blended set of metrics.
- building_block = ETFs / crypto (Bonds, Broad market, Gold, Crypto asset) -> per-member metrics + range,
                   NO blended figure (e.g. near-cash ZST.TO and long-Treasury TLT are too different to average).

Return contract and JSON-safety: see AGENT_GUARDRAILS.md / agents/risk_analyst.agent.md. Never raises.
Risk label thresholds are team assumptions from CLAUDE.md.
"""
import math

import pandas as pd

from workers import data_retriever as dr

DAYS_STOCK, DAYS_CRYPTO = 252, 365
# 2022 return measured from the last 2021 close (2021-12-31) to the last 2022 close
STRESS_START, STRESS_END = "2021-12-31", "2022-12-31"
LABELS = ["Low", "Moderate", "High", "Very High"]
RANGE_METRICS = ("annualized_vol", "max_drawdown", "total_return")


# ---------- pure helpers ----------

def risk_label(vol: float, max_drawdown: float) -> tuple[str, str]:
    """Vol < 10% Low, 10-20% Moderate, 20-35% High, > 35% Very High; drawdown worse than -30% bumps one level."""
    i = 0 if vol < 0.10 else 1 if vol < 0.20 else 2 if vol <= 0.35 else 3
    reason = f"vol {vol:.1%} -> {LABELS[i]}"
    if max_drawdown < -0.30 and i < 3:
        i += 1
        reason += f"; max drawdown {max_drawdown:.1%} worse than -30% -> bumped to {LABELS[i]}"
    return LABELS[i], reason


def metrics(prices: pd.Series, days_per_year: int) -> dict:
    """Metrics from a price (or index) series sorted by date. Needs at least 2 prices."""
    rets = prices.pct_change().dropna()
    total = prices.iloc[-1] / prices.iloc[0] - 1
    vol = rets.std(ddof=1) * math.sqrt(days_per_year)
    mdd = (prices / prices.cummax() - 1).min()
    label, reason = risk_label(vol, mdd)
    return {"total_return": float(total),
            "annualized_return": float((1 + total) ** (days_per_year / len(rets)) - 1),
            "annualized_vol": float(vol),
            "max_drawdown": float(mdd),
            "current_drawdown": float(prices.iloc[-1] / prices.max() - 1),
            "n_returns": int(len(rets)),
            "days_per_year": days_per_year,
            "risk_label": label,
            "risk_label_reason": reason}


def _err(msg):
    return {"status": "error", "error": msg}


def _ok(data, src, period, ccy, warnings):
    return {"status": "ok", "data": data, "source": src, "period": period, "currency": ccy, "warnings": warnings}


def _price_frame(tickers, start, end, currency):
    """Wide DataFrame (date x ticker) of adj_close from data_retriever, plus the retriever result."""
    res = dr.get_prices(tickers, start, end, currency)
    if res["status"] != "ok":
        return None, res
    cols = {t: pd.Series({pd.Timestamp(r["date"]): r["adj_close"] for r in rows}) for t, rows in res["data"].items()}
    return pd.DataFrame(cols).sort_index(), res


def _universe() -> list[dict]:
    return dr.get_universe().get("data", [])


def _period(idx) -> dict:
    return {"start": idx.min().strftime("%Y-%m-%d"), "end": idx.max().strftime("%Y-%m-%d")}


def sector_members(sector: str) -> list[dict]:
    """Universe rows for a sector: exact label, or group = label text before ' (' (e.g. 'Bonds')."""
    u = _universe()
    exact = [r for r in u if r["sector"] == sector]
    return exact or [r for r in u if r["sector"].split(" (")[0] == sector]


def equal_weight_index(df: pd.DataFrame) -> pd.Series:
    """Equal-weight index (starts at 1.0), rebalanced daily, from a date x ticker price frame on common dates."""
    df = df.dropna()
    ret = df.pct_change().dropna().mean(axis=1)
    return pd.concat([pd.Series([1.0], index=[df.index[0]]), (1 + ret).cumprod()])


def group_kind(members: list[dict]) -> str:
    """'industry' if every member is an equity, else 'building_block'."""
    return "industry" if all(m["asset_class"] == "equity" for m in members) else "building_block"


# ---------- public functions ----------

def analyze_asset(ticker: str, start: str, end: str, currency: str = "CAD") -> dict:
    """Return, annualized vol, max/current drawdown and risk label for one asset over [start, end].

    For assets listed in another currency (e.g. AGG in USD) also returns the vol in the listing currency,
    so the difference shows how much of the risk comes from the exchange rate.
    """
    try:
        df, res = _price_frame([ticker], start, end, currency)
        if df is None:
            return res
        p = df[ticker].dropna()
        if len(p) < 3:  # 2 prices = 1 return: volatility undefined (NaN)
            return _err(f"{ticker}: fewer than 3 prices between {start} and {end}")
        info = next(r for r in _universe() if r["ticker"] == ticker)
        dpy = DAYS_CRYPTO if info["asset_class"] == "crypto" else DAYS_STOCK
        warnings = list(res["warnings"])
        if len(p) - 1 < 252:
            warnings.append(f"{ticker}: only {len(p) - 1} daily returns (< 252), metrics less reliable")
        data = {"ticker": ticker, "name": info["name"], "asset_class": info["asset_class"],
                "sector": info["sector"], **metrics(p, dpy)}
        local = info["currency"]
        if local != currency:
            ldf, _ = _price_frame([ticker], start, end, local)
            if ldf is not None:
                lv = metrics(ldf[ticker].dropna(), dpy)["annualized_vol"]
                data["listing_currency_vol"] = {"currency": local, "annualized_vol": lv,
                                                "fx_effect": data["annualized_vol"] - lv}
        return _ok(data, res["source"], _period(p.index), currency, warnings)
    except Exception as e:
        return _err(f"analyze_asset failed: {e}")


def analyze_sector(sector: str, start: str, end: str, currency: str = "CAD") -> dict:
    """Analyze a group from the universe `sector` column (exact label or prefix, e.g. 'Bonds').

    industry (all equities): equal-weight basket, daily rebalanced on common dates -> one set of metrics,
      plus member_metrics.
    building_block (ETFs/crypto): member_metrics and the min-max range per metric, no blended figure.
    """
    try:
        members = sector_members(sector)
        if not members:
            return _err(f"unknown sector '{sector}'")
        kind = group_kind(members)
        tickers = [m["ticker"] for m in members]
        warnings = []
        if len(tickers) == 1:
            warnings.append("sector = 1 asset, not diversified")

        if kind == "building_block":
            results = {t: analyze_asset(t, start, end, currency) for t in tickers}
            ok = {t: r for t, r in results.items() if r["status"] == "ok"}
            if not ok:
                return _err("; ".join(r["error"] for r in results.values()))
            warnings += [f"{t}: {r['error']}" for t, r in results.items() if r["status"] != "ok"]
            warnings += [w for r in ok.values() for w in r["warnings"]]
            warnings.append("building block: members reported separately, no blended figure")
            mm = {t: r["data"] for t, r in ok.items()}
            rng = {}
            for k in RANGE_METRICS:
                lo, hi = min(mm, key=lambda t: mm[t][k]), max(mm, key=lambda t: mm[t][k])
                rng[k] = {"min": mm[lo][k], "min_ticker": lo, "max": mm[hi][k], "max_ticker": hi}
            starts = [r["period"]["start"] for r in ok.values()]
            ends = [r["period"]["end"] for r in ok.values()]
            data = {"sector": sector, "kind": kind, "members": list(mm), "member_metrics": mm, "range": rng}
            src = next(iter(ok.values()))["source"]
            return _ok(data, src, {"start": min(starts), "end": max(ends)}, currency, warnings)

        df, res = _price_frame(tickers, start, end, currency)
        if df is None:
            return res
        warnings += res["warnings"]
        missing = [t for t in tickers if t not in df.columns]
        if missing:
            warnings.append(f"members without data excluded: {missing}")
        tickers = [t for t in tickers if t in df.columns]
        df = df[tickers].dropna()  # common dates only
        if len(df) < 3:
            return _err(f"sector '{sector}': fewer than 3 common dates between {start} and {end}")
        w = 1 / len(tickers)
        index = equal_weight_index(df)
        if len(index) - 1 < 252:
            warnings.append(f"only {len(index) - 1} daily returns (< 252), metrics less reliable")
        warnings.append("sector = equal-weight basket of universe assets, rebalanced daily, common dates only")
        data = {"sector": sector, "kind": kind, "members": tickers, "weights": {t: w for t in tickers},
                **metrics(index, DAYS_STOCK),
                "member_metrics": {t: metrics(df[t], DAYS_STOCK) for t in tickers}}
        return _ok(data, res["source"], _period(df.index), currency, warnings)
    except Exception as e:
        return _err(f"analyze_sector failed: {e}")


def correlation(tickers, start: str, end: str) -> dict:
    """Pearson correlation of daily returns (CAD), on common dates only."""
    try:
        df, res = _price_frame(tickers, start, end, "CAD")
        if df is None:
            return res
        rets = df.dropna().pct_change().dropna()
        if len(rets) < 2 or rets.shape[1] < 2:
            return _err("need at least 2 tickers with at least 3 common dates")
        c = rets.corr()
        data = {"matrix": {a: {b: float(c.loc[a, b]) for b in c.columns} for a in c.index},
                "n_common_returns": int(len(rets))}
        return _ok(data, res["source"], _period(rets.index), "CAD", res["warnings"] + ["computed on common dates only"])
    except Exception as e:
        return _err(f"correlation failed: {e}")


def stress_test_2022(tickers_or_sector, currency: str = "CAD") -> dict:
    """Total return and max drawdown in calendar 2022 for a sector name, a ticker, or a list of tickers.

    Industry sector -> one entry for the basket; building block -> one entry per member.
    """
    try:
        def summary(d):
            return {"total_return": d["total_return"], "max_drawdown": d["max_drawdown"],
                    "annualized_vol": d["annualized_vol"], "risk_label": d["risk_label"]}

        if isinstance(tickers_or_sector, str) and sector_members(tickers_or_sector):
            r = analyze_sector(tickers_or_sector, STRESS_START, STRESS_END, currency)
            if r["status"] != "ok":
                return r
            d = r["data"]
            data = ({tickers_or_sector: summary(d)} if d["kind"] == "industry"
                    else {t: summary(m) for t, m in d["member_metrics"].items()})
            return _ok(data, r["source"], r["period"], currency, r["warnings"])
        items = [tickers_or_sector] if isinstance(tickers_or_sector, str) else list(tickers_or_sector)
        data, warnings, src, period = {}, [], None, None
        for t in items:
            r = analyze_asset(t, STRESS_START, STRESS_END, currency)
            if r["status"] != "ok":
                warnings.append(f"{t}: {r['error']}")
                continue
            data[t], src, period = summary(r["data"]), r["source"], r["period"]
            warnings += r["warnings"]
        if not data:
            return _err("; ".join(warnings) or "nothing to test")
        return _ok(data, src, period, currency, warnings)
    except Exception as e:
        return _err(f"stress_test_2022 failed: {e}")
