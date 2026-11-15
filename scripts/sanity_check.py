"""Independent sanity check of the workers against the raw CSVs. Run from the repo root: PYTHONPATH=. python scripts/sanity_check.py"""
import math

import pandas as pd

from workers import risk_analyst as ra, suitability as su, market_context as mc

P = pd.read_csv("data/prices_daily.csv", parse_dates=["date"])
FX = pd.read_csv("data/fx_usdcad_daily.csv", parse_dates=["date"]).sort_values("date")
results = []


def ok(name, cond, detail=""):
    results.append((name, bool(cond), detail))


def raw_cad(ticker, start, end):
    """adj_close in CAD built from raw CSVs with merge_asof backward, independent of data_retriever."""
    s = P[P.ticker == ticker].sort_values("date")[["date", "adj_close", "currency"]]
    if s.currency.iloc[0] == "USD":
        s = pd.merge_asof(s, FX[["date", "usdcad"]], on="date", direction="backward")
        s["adj_close"] = s.adj_close * s.usdcad
    s = s[(s.date >= start) & (s.date <= end)]
    return s.set_index("date").adj_close


def raw_metrics(ticker, start, end, dpy):
    p = raw_cad(ticker, start, end)
    r = p.pct_change().dropna()
    return {"total_return": p.iloc[-1] / p.iloc[0] - 1, "annualized_vol": r.std() * math.sqrt(dpy),
            "max_drawdown": (p / p.cummax() - 1).min()}


S, E = "2021-11-12", "2026-11-12"

# 1. Worker numbers equal an independent recomputation from raw CSVs
for t, dpy in [("NVDA", 252), ("SPY", 252), ("XBB.TO", 252), ("BTC-USD", 365), ("TLT", 252)]:
    w = ra.analyze_asset(t, S, E)["data"]
    r = raw_metrics(t, S, E, dpy)
    diffs = {k: abs(w[k] - r[k]) for k in r}
    ok(f"{t}: worker == raw recompute (CAD)", max(diffs.values()) < 1e-9,
       f"vol {w['annualized_vol']:.2%}, ret {w['total_return']:.2%}, mdd {w['max_drawdown']:.2%}, label {w['risk_label']}")

# 2. Plausibility
vol = {t: ra.analyze_asset(t, S, E)["data"]["annualized_vol"] for t in ["XBB.TO", "AGG", "ZST.TO", "SPY", "QQQ", "BTC-USD", "NVDA"]}
ok("bond vol < equity vol", max(vol["XBB.TO"], vol["ZST.TO"]) < vol["SPY"],
   f"XBB {vol['XBB.TO']:.1%}, ZST {vol['ZST.TO']:.1%}, AGG {vol['AGG']:.1%} vs SPY {vol['SPY']:.1%}")
ok("ZST.TO (ultra-short) vol < 3%", vol["ZST.TO"] < 0.03, f"{vol['ZST.TO']:.2%}")
ok("BTC vol > 2x SPY", vol["BTC-USD"] > 2 * vol["SPY"], f"BTC {vol['BTC-USD']:.1%} vs SPY {vol['SPY']:.1%}")
ok("NVDA vol > QQQ vol > SPY vol", vol["NVDA"] > vol["QQQ"] > vol["SPY"],
   f"NVDA {vol['NVDA']:.1%}, QQQ {vol['QQQ']:.1%}, SPY {vol['SPY']:.1%}")
st = ra.stress_test_2022(["SPY", "QQQ", "TLT", "XOM", "GLD"])["data"]
ok("2022 negative for SPY, QQQ, TLT", all(st[t]["total_return"] < 0 for t in ["SPY", "QQQ", "TLT"]),
   ", ".join(f"{t} {st[t]['total_return']:.1%}" for t in st))
ok("2022 XOM positive (energy rally)", st["XOM"]["total_return"] > 0, f"{st['XOM']['total_return']:.1%}")

# SPY 2022 in USD vs public figure (~-18.2% total return)
spy_usd = P[(P.ticker == "SPY") & (P.date >= "2021-12-31") & (P.date <= "2022-12-31")].sort_values("date").adj_close
spy_ret = spy_usd.iloc[-1] / spy_usd.iloc[0] - 1
ok("SPY 2022 USD total return near public -18.2%", abs(spy_ret - (-0.182)) < 0.01, f"{spy_ret:.2%}")

# 3. Sector basket = mean of member daily returns, weights sum to 1
it = ra.analyze_sector("Information Technology", S, E)["data"]
ok("IT weights sum to 1", abs(sum(it["weights"].values()) - 1) < 1e-12, f"members {it['members']}")
df = pd.DataFrame({t: raw_cad(t, S, E) for t in it["members"]}).dropna()
idx = (1 + df.pct_change().dropna().mean(axis=1)).cumprod()
ok("IT basket total return == raw recompute", abs((idx.iloc[-1] - 1) - it["total_return"]) < 1e-9,
   f"{it['total_return']:.2%}, vol {it['annualized_vol']:.1%}, label {it['risk_label']}")

# 4. Correlation sanity
c = ra.correlation(["SPY", "QQQ", "TLT"], S, E)["data"]["matrix"]
ok("corr(SPY,QQQ) > 0.85", c["SPY"]["QQQ"] > 0.85, f"{c['SPY']['QQQ']:.2f}; SPY-TLT {c['SPY']['TLT']:.2f}")

# 5. No look-ahead: end date respected
r = ra.analyze_asset("SPY", "2022-01-01", "2022-06-30")
ok("period end <= requested end", r["period"]["end"] <= "2022-06-30", str(r["period"]))

# 6. Demo scenarios through suitability
rob = su.check("robert", "NVDA", 0.5)["data"]
ok("Robert NVDA 50% -> conflict", rob["overall"] == "conflict",
   "; ".join(f"{c['rule']}={c['status']}" for c in rob["checks"]))
rob_btc = su.check("robert", "BTC-USD")["data"]
ok("Robert BTC -> conflict", rob_btc["overall"] == "conflict")
rob_bonds = su.check("robert", "Bonds")["data"]
ok("Robert Bonds -> not conflict", rob_bonds["overall"] != "conflict",
   "; ".join(f"{c['rule']}={c['status']}" for c in rob_bonds["checks"]))
am = su.check("amira", "BTC-USD", 0.20)["data"]
ok("Amira BTC 20% -> conflict (cap 15%)", am["overall"] == "conflict")
am_it = su.check("amira", "Information Technology", 0.40)["data"]
ok("Amira IT 40% -> not conflict", am_it["overall"] != "conflict",
   "; ".join(f"{c['rule']}={c['status']}" for c in am_it["checks"]))
ma = su.check("mateo", "Energy")["data"]
esg = next(c for c in ma["checks"] if c["rule"] == "esg_review")
ok("Mateo Energy -> ESG flag on ENB/CNQ/XOM", esg["status"] == "flag", str(esg["value"]))
ma_u = su.check("mateo", "Utilities")["data"]
ok("Mateo Utilities -> ESG pass", next(c for c in ma_u["checks"] if c["rule"] == "esg_review")["status"] == "pass")

# 7. Market context on the analysis end date
cy = mc.cycle_phase(E)
ok("cycle_phase ok", cy["status"] == "ok", f"{cy.get('data', {}).get('phase')} | warnings {cy.get('warnings')}")
fh = mc.fear_hope(E)
ok("fear_hope ok", fh["status"] == "ok", str({k: v for k, v in fh.get("data", {}).items() if not isinstance(v, (list, dict))}))
mo = mc.sector_momentum("Utilities", E)
ok("sector_momentum Utilities ok", mo["status"] == "ok", mo.get("error", ""))

# 8. Error dicts, never raise
for name, call in [("unknown ticker", lambda: ra.analyze_asset("ZZZZ", S, E)),
                   ("empty range", lambda: ra.analyze_asset("SPY", "2030-01-01", "2030-02-01")),
                   ("bad persona", lambda: su.check("bob", "SPY")),
                   ("bad weight", lambda: su.check("robert", "SPY", 1.5)),
                   ("unknown sector", lambda: mc.sector_momentum("Nope", E))]:
    out = call()
    ok(f"error dict: {name}", out.get("status") == "error", out.get("error", ""))

w = max(len(n) for n, _, _ in results)
for n, passed, d in results:
    print(f"{'PASS' if passed else 'FAIL'}  {n:<{w}}  {d}")
print(f"\n{sum(p for _, p, _ in results)}/{len(results)} checks passed")
