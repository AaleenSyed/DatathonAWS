"""market_context worker: business-cycle phase (FRED rules), fear vs hope (VIX, credit spread, sentiment),
sector momentum / trend / relative strength (from prices). Deterministic, no LLM.

Rules and thresholds are team assumptions from CLAUDE.md ("Market context rules"). They describe historical
tendencies, NOT predictions: every phase/tilt is returned with claim_type "assumption" and the signal values
and dates that triggered it. Only values published by `as_of` are used (data_retriever.get_macro(as_of=...)).
Return contract / JSON-safety: see AGENT_GUARDRAILS.md. Never raises.
"""
import pandas as pd

from workers import data_retriever as dr
from workers import risk_analyst as ra

# CLAUDE.md sector rotation tendencies
CYCLE_TILT = {
    "Early cycle": ["Financials", "Consumer Discretionary", "Industrials"],
    "Mid cycle": ["Information Technology", "Industrials", "Communication Services"],
    "Late cycle": ["Energy", "Health Care", "Consumer Staples"],
    "Recession risk": ["Utilities", "Consumer Staples", "Health Care", "Bonds"],
}
SAHM_TRIGGER, RECPRO_TRIGGER = 0.5, 30.0        # CLAUDE.md
VIX_CALM, VIX_FEAR = 15.0, 25.0                  # CLAUDE.md
LOOKBACK = pd.DateOffset(months=12)              # CLAUDE.md "past 12 months"
INDPRO_RISING = pd.DateOffset(months=3)          # team assumption: "rising" = latest > value 3 months earlier
SPREAD_CHANGE = pd.DateOffset(months=3)          # team assumption: credit spread change over 3 months
SENTIMENT_CHANGE = pd.DateOffset(months=12)
CYCLE_SERIES = ["SAHMREALTIME", "RECPROUSM156N", "T10Y2Y", "INDPRO"]
MOOD_SERIES = ["VIXCLS", "BAMLH0A0HYM2", "UMCSENT"]
BENCHMARK = {"CA": "XIU.TO", "US": "SPY"}        # CLAUDE.md relative strength benchmarks


def _err(msg):
    return {"status": "error", "error": msg}


def _ok(data, src, period, ccy, warnings):
    return {"status": "ok", "data": data, "source": src, "period": period, "currency": ccy, "warnings": warnings}


def _macro(series, as_of, years=2):
    """{sid: DataFrame(date, available_date, value)} of values published by as_of, plus the get_macro result."""
    a = pd.Timestamp(as_of)
    res = dr.get_macro(series, (a - pd.DateOffset(years=years)).strftime("%Y-%m-%d"), a.strftime("%Y-%m-%d"),
                       as_of=a.strftime("%Y-%m-%d"))
    if res["status"] != "ok":
        return {}, res
    frames = {sid: pd.DataFrame(rows).assign(date=lambda d: pd.to_datetime(d["date"]),
                                             available_date=lambda d: pd.to_datetime(d["available_date"]))
              for sid, rows in res["data"].items()}
    return frames, res


def _latest(df):
    r = df.iloc[-1]
    return {"value": float(r["value"]), "date": r["date"].strftime("%Y-%m-%d"),
            "available_date": r["available_date"].strftime("%Y-%m-%d")}


def _value_on_or_before(df, d):
    rows = df[df["date"] <= d]
    return None if rows.empty else rows.iloc[-1]


# ---------- business cycle ----------

def cycle_phase(as_of: str) -> dict:
    """Business-cycle phase from FRED signals published by `as_of` (CLAUDE.md rules, checked in this order):
    Recession risk: SAHMREALTIME >= 0.5 or RECPROUSM156N >= 30.
    Early cycle: a recession signal in the past 12 months (not now) and INDPRO rising (latest > 3 months earlier).
    Late cycle: T10Y2Y < 0 now or at any point in the past 12 months, and no recession signal.
    Mid cycle: otherwise.
    """
    try:
        a = pd.Timestamp(as_of)
        m, res = _macro(CYCLE_SERIES, a)
        if not m:
            return res
        warnings = list(res["warnings"])
        missing = [s for s in CYCLE_SERIES if s not in m]
        if missing:
            warnings.append(f"series not available by {a.date()}: {missing}; rules using them not evaluated")
        signals = {s: {**_latest(df), "unit": res["units"].get(s)} for s, df in m.items()}

        def rec_mask(sid, trigger):
            return m[sid]["value"] >= trigger if sid in m else None

        sahm, rec = rec_mask("SAHMREALTIME", SAHM_TRIGGER), rec_mask("RECPROUSM156N", RECPRO_TRIGGER)
        recession_now = any(mask is not None and bool(mask.iloc[-1]) for mask in (sahm, rec))
        recession_12m = any(mask is not None and bool(mask[m[s]["available_date"] > a - LOOKBACK].any())
                            for s, mask in (("SAHMREALTIME", sahm), ("RECPROUSM156N", rec)))
        flags = {"recession_signal_now": recession_now, "recession_signal_past_12m": recession_12m}

        if "T10Y2Y" in m:
            t = m["T10Y2Y"]
            flags["curve_inverted_now"] = bool(t["value"].iloc[-1] < 0)
            flags["curve_inverted_past_12m"] = bool((t.loc[t["date"] > a - LOOKBACK, "value"] < 0).any())
        indpro_rising = None
        if "INDPRO" in m:
            ip = m["INDPRO"]
            prev = _value_on_or_before(ip, ip["date"].iloc[-1] - INDPRO_RISING)
            if prev is not None:
                indpro_rising = bool(ip["value"].iloc[-1] > prev["value"])
                signals["INDPRO"]["value_3m_earlier"] = float(prev["value"])
                signals["INDPRO"]["date_3m_earlier"] = prev["date"].strftime("%Y-%m-%d")
        flags["indpro_rising"] = indpro_rising

        if recession_now:
            phase, rule = "Recession risk", (f"SAHMREALTIME >= {SAHM_TRIGGER} or RECPROUSM156N >= {RECPRO_TRIGGER}"
                                             " in the latest published value")
        elif recession_12m and indpro_rising:
            phase, rule = "Early cycle", "recession signal in the past 12 months and INDPRO rising over 3 months"
        elif flags.get("curve_inverted_now") or flags.get("curve_inverted_past_12m"):
            phase, rule = "Late cycle", "T10Y2Y < 0 now or in the past 12 months, no recession signal now"
        else:
            phase, rule = "Mid cycle", "no recession signal, no inversion in the past 12 months, no early-cycle signal"
        tilt = CYCLE_TILT[phase]
        data = {"as_of": a.strftime("%Y-%m-%d"), "phase": phase, "rule_fired": rule, "flags": flags,
                "signals": signals, "sector_tilt": tilt, "claim_type": "assumption",
                "statement": f"Historically, in a {phase.lower()} phase, sectors like {', '.join(tilt)} have tended "
                             "to do relatively well. This is a historical tendency, not a prediction."}
        return _ok(data, res["source"], res["period"], None, warnings)
    except Exception as e:
        return _err(f"cycle_phase failed: {e}")


# ---------- fear vs hope ----------

def vix_mood(vix: float) -> str:
    """VIX < 15 calm/hope, 15-25 normal, > 25 fear (CLAUDE.md)."""
    return "calm/hope" if vix < VIX_CALM else "fear" if vix > VIX_FEAR else "normal"


def fear_hope(as_of: str) -> dict:
    """Market mood from VIX level, 3-month change in the high-yield credit spread, and consumer sentiment."""
    try:
        a = pd.Timestamp(as_of)
        m, res = _macro(MOOD_SERIES, a)
        if not m:
            return res
        warnings, data = list(res["warnings"]), {"as_of": a.strftime("%Y-%m-%d"), "claim_type": "assumption"}
        if "VIXCLS" in m:
            v = _latest(m["VIXCLS"])
            data["vix"] = {**v, "mood": vix_mood(v["value"])}
        else:
            data["vix"] = None
            warnings.append("VIX not available")
        hy = m.get("BAMLH0A0HYM2")
        prev = None if hy is None else _value_on_or_before(hy, hy["date"].iloc[-1] - SPREAD_CHANGE)
        if prev is None:
            data["credit_spread"] = None
            warnings.append("high-yield credit spread not available for this date (FRED only serves the last "
                            "3 years of this ICE BofA series)")
        else:
            cur = _latest(hy)
            change = float(cur["value"] - prev["value"])
            data["credit_spread"] = {**cur, "value_3m_earlier": float(prev["value"]),
                                     "date_3m_earlier": prev["date"].strftime("%Y-%m-%d"),
                                     "change_3m": change, "rising_stress": bool(change > 0)}
        um = m.get("UMCSENT")
        if um is not None:
            cur = _latest(um)
            p12 = _value_on_or_before(um, um["date"].iloc[-1] - SENTIMENT_CHANGE)
            data["consumer_sentiment"] = {**cur, "change_12m": None if p12 is None else float(cur["value"] - p12["value"])}
        mood = data["vix"]["mood"] if data["vix"] else "unknown"
        stress = bool(data["credit_spread"] and data["credit_spread"]["rising_stress"])
        data["mood"] = mood
        data["statement"] = (f"VIX-based mood: {mood}" + ("; credit spreads rising over 3 months (stress signal)"
                                                         if stress else ""))
        return _ok(data, res["source"], res["period"], None, warnings)
    except Exception as e:
        return _err(f"fear_hope failed: {e}")


# ---------- momentum / trend / relative strength ----------

def _country(ticker):
    return "CA" if ticker.endswith(".TO") else "US"


def trend_metrics(p: pd.Series, bench: pd.Series, as_of: pd.Timestamp) -> dict:
    """6/12-month momentum, 12-month relative strength vs benchmark, price vs 200-obs average, drawdown from
    12-month high. Price series indexed by date, ending on/before as_of."""
    def mom(s, months):
        past = s[s.index <= as_of - pd.DateOffset(months=months)]
        return None if past.empty else float(s.iloc[-1] / past.iloc[-1] - 1)
    out = {"price_date": p.index[-1].strftime("%Y-%m-%d"),
           "momentum_6m": mom(p, 6), "momentum_12m": mom(p, 12)}
    b12 = mom(bench, 12)
    out["benchmark_return_12m"] = b12
    out["relative_strength_12m"] = None if out["momentum_12m"] is None or b12 is None else out["momentum_12m"] - b12
    if len(p) >= 200:
        sma = p.iloc[-200:].mean()
        out["price_vs_200d_avg"] = float(p.iloc[-1] / sma - 1)
        out["trend"] = "above 200-day average" if p.iloc[-1] > sma else "below 200-day average"
    else:
        out["price_vs_200d_avg"], out["trend"] = None, "not available (< 200 observations)"
    high = p[p.index > as_of - pd.DateOffset(months=12)].max()
    out["drawdown_from_12m_high"] = float(p.iloc[-1] / high - 1)
    return out


def sector_momentum(sector_or_ticker: str, as_of: str, currency: str = "CAD") -> dict:
    """Momentum and trend for a ticker or a sector group, using prices up to `as_of` (CAD by default).

    Benchmark: XIU.TO for .TO tickers, SPY for the rest. Industry -> equal-weight basket vs an equal-weight basket
    of the members' benchmarks, plus per-member metrics. Building block -> per-member metrics only.
    """
    try:
        a = pd.Timestamp(as_of)
        members = ra.sector_members(sector_or_ticker)
        if members:
            tickers, kind = [r["ticker"] for r in members], ra.group_kind(members)
        else:
            info = dr.get_asset_info(sector_or_ticker)
            if info["status"] != "ok":
                return _err(f"unknown sector or ticker '{sector_or_ticker}'")
            tickers, kind = [sector_or_ticker], "asset"
        start = (a - pd.DateOffset(months=24)).strftime("%Y-%m-%d")
        df, res = ra._price_frame(list(dict.fromkeys(tickers + list(BENCHMARK.values()))), start,
                                  a.strftime("%Y-%m-%d"), currency)
        if df is None:
            return res
        warnings = list(res["warnings"])
        if df.index.min() > a - pd.DateOffset(months=12):
            warnings.append("less than 12 months of prices before as_of; 12-month metrics not available")
        per = {}
        for t in tickers:
            if t not in df:
                warnings.append(f"{t}: no prices")
                continue
            per[t] = {"benchmark": BENCHMARK[_country(t)],
                      **trend_metrics(df[t].dropna(), df[BENCHMARK[_country(t)]].dropna(), a)}
        if not per:
            return _err("no prices for any member")
        data = {"target": sector_or_ticker, "kind": kind, "as_of": a.strftime("%Y-%m-%d"), "members": per}
        if kind == "industry":
            idx = ra.equal_weight_index(df[list(per)])
            bench = ra.equal_weight_index(pd.concat({t: df[BENCHMARK[_country(t)]] for t in per}, axis=1))
            data["basket"] = {"benchmark": "equal-weight mix of members' benchmarks",
                              **trend_metrics(idx, bench, a)}
            warnings.append("industry basket = equal weight, rebalanced daily, common dates only")
        if any(r["asset_class"] == "crypto" for r in members):
            warnings.append("crypto: 200 observations = 200 calendar days")
        return _ok(data, res["source"], res["period"], currency, warnings)
    except Exception as e:
        return _err(f"sector_momentum failed: {e}")
