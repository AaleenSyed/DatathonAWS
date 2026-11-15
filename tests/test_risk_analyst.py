import json
import math
import statistics

import pandas as pd
import pytest

from workers import data_retriever as dr
from workers import risk_analyst as ra

has_data = pytest.mark.skipif(not (dr.DATA_DIR / "prices_daily.csv").exists(), reason="starter data not in data/")
FULL = ("2021-11-12", "2026-11-12")


def ok(res):
    json.dumps(res, allow_nan=False)
    assert res["status"] == "ok", res
    return res["data"]


# ---------- hand-computed checks on a synthetic series ----------

def test_metrics_hand_check():
    p = pd.Series([100.0, 110.0, 99.0, 105.0], index=pd.date_range("2024-01-01", periods=4))
    m = ra.metrics(p, 252)
    rets = [110 / 100 - 1, 99 / 110 - 1, 105 / 99 - 1]
    assert m["annualized_vol"] == pytest.approx(statistics.stdev(rets) * math.sqrt(252))
    assert m["max_drawdown"] == pytest.approx(99 / 110 - 1)
    assert m["total_return"] == pytest.approx(0.05)
    assert m["annualized_return"] == pytest.approx(1.05 ** (252 / 3) - 1)
    assert m["current_drawdown"] == pytest.approx(105 / 110 - 1)


@pytest.mark.parametrize("vol,mdd,label", [
    (0.0999, -0.05, "Low"), (0.10, -0.05, "Moderate"), (0.1999, -0.05, "Moderate"), (0.20, -0.05, "High"),
    (0.35, -0.05, "High"), (0.3501, -0.05, "Very High"),
    (0.15, -0.30, "Moderate"),   # exactly -30% is not "worse than"
    (0.15, -0.31, "High"),       # bump
    (0.05, -0.40, "Moderate"),
    (0.50, -0.80, "Very High"),  # cannot bump past Very High
])
def test_risk_label_boundaries(vol, mdd, label):
    assert ra.risk_label(vol, mdd)[0] == label


# ---------- groups with stubbed data ----------

A, B = [100, 102, 101, 104], [50, 49, 50, 51]


@pytest.fixture
def stub_two(monkeypatch):
    """Two stub assets A, B in one group; asset_class set by the test."""
    dates = pd.date_range("2024-01-01", periods=4).strftime("%Y-%m-%d")

    def setup(asset_class):
        monkeypatch.setattr(dr, "get_universe", lambda: {"status": "ok", "data": [
            {"ticker": t, "name": t, "asset_class": asset_class, "sector": f"Test ({t})", "currency": "CAD"}
            for t in "AB"]})
        monkeypatch.setattr(dr, "get_prices", lambda t, s, e, c="CAD": {
            "status": "ok", "source": "stub", "warnings": [], "currency": c, "period": {},
            "data": {k: [{"date": d, "adj_close": v} for d, v in zip(dates, vals)]
                     for k, vals in {"A": A, "B": B}.items() if k in ([t] if isinstance(t, str) else t)}})
    return setup


def test_industry_is_equal_weight_basket(stub_two):
    stub_two("equity")
    d = ok(ra.analyze_sector("Test", "2024-01-01", "2024-01-04"))
    idx = 1.0
    for i in range(1, 4):
        idx *= 1 + 0.5 * (A[i] / A[i - 1] - 1) + 0.5 * (B[i] / B[i - 1] - 1)
    assert d["kind"] == "industry" and d["total_return"] == pytest.approx(idx - 1)
    assert d["weights"] == {"A": 0.5, "B": 0.5}


def test_building_block_has_no_blended_figure(stub_two):
    stub_two("etf_bond")
    d = ok(ra.analyze_sector("Test", "2024-01-01", "2024-01-04"))
    assert d["kind"] == "building_block" and "annualized_vol" not in d and "weights" not in d
    assert d["range"]["total_return"] == {"min": B[-1] / B[0] - 1, "min_ticker": "B",
                                          "max": A[-1] / A[0] - 1, "max_ticker": "A"}


# ---------- sanity on real data ----------

@has_data
def test_sanity_vol_ordering():
    vol = {t: ok(ra.analyze_asset(t, *FULL))["annualized_vol"] for t in ["XBB.TO", "AGG", "SPY", "BTC-USD"]}
    assert vol["XBB.TO"] < vol["SPY"] / 2 and vol["AGG"] < vol["SPY"] / 2
    assert vol["BTC-USD"] > vol["SPY"] * 2


@has_data
def test_2022_negative_for_spy_qqq_tlt():
    d = ok(ra.stress_test_2022(["SPY", "QQQ", "TLT"]))
    assert all(d[t]["total_return"] < 0 for t in ["SPY", "QQQ", "TLT"])


@has_data
def test_crypto_uses_365_others_252():
    assert ok(ra.analyze_asset("BTC-USD", *FULL))["days_per_year"] == 365
    assert ok(ra.analyze_asset("SPY", *FULL))["days_per_year"] == 252
    assert all(m["days_per_year"] == 365 for m in ok(ra.analyze_sector("Crypto asset", *FULL))["member_metrics"].values())


@has_data
@pytest.mark.parametrize("sector,n,kind", [
    ("Bonds", 4, "building_block"), ("Broad market", 4, "building_block"), ("Gold", 1, "building_block"),
    ("Crypto asset", 2, "building_block"), ("Bonds (U.S. long Treasury)", 1, "building_block"),
    ("Information Technology", 5, "industry"), ("Energy", 3, "industry"), ("Utilities", 1, "industry")])
def test_group_kind_and_members(sector, n, kind):
    d = ok(ra.analyze_sector(sector, *FULL))
    assert len(d["members"]) == n and d["kind"] == kind
    if kind == "industry":
        assert sum(d["weights"].values()) == pytest.approx(1)


@has_data
def test_bonds_range_spans_members():
    d = ok(ra.analyze_sector("Bonds", *FULL))
    vols = {t: m["annualized_vol"] for t, m in d["member_metrics"].items()}
    assert d["range"]["annualized_vol"]["min"] == min(vols.values())
    assert d["range"]["annualized_vol"]["max_ticker"] == max(vols, key=vols.get)


@has_data
def test_usd_asset_reports_listing_currency_vol():
    d = ok(ra.analyze_asset("AGG", *FULL))
    p = dr._load("prices_daily.csv")
    usd = p[p.ticker == "AGG"].set_index("date").adj_close
    hand = usd.pct_change().dropna().std(ddof=1) * math.sqrt(252)  # hand check from raw USD prices
    assert d["listing_currency_vol"]["currency"] == "USD"
    assert d["listing_currency_vol"]["annualized_vol"] == pytest.approx(hand)
    assert "listing_currency_vol" not in ok(ra.analyze_asset("XBB.TO", *FULL))


@has_data
def test_single_asset_sector_warns():
    r = ra.analyze_sector("Utilities", *FULL)
    assert any("1 asset" in w for w in r["warnings"])


@has_data
def test_correlation_symmetric_and_diag_one():
    m = ok(ra.correlation(["SPY", "QQQ", "TLT"], *FULL))["matrix"]
    assert m["SPY"]["SPY"] == pytest.approx(1) and m["SPY"]["QQQ"] == pytest.approx(m["QQQ"]["SPY"])
    assert m["SPY"]["QQQ"] > m["SPY"]["TLT"]


@has_data
def test_stress_sector_by_name():
    d = ok(ra.stress_test_2022("Information Technology"))
    assert "Information Technology" in d


# ---------- edge cases ----------

@has_data
@pytest.mark.parametrize("call", [
    lambda: ra.analyze_asset("NOPE", *FULL),
    lambda: ra.analyze_asset("SPY", "2022-12-31", "2022-01-01"),
    lambda: ra.analyze_asset("SPY", "1990-01-01", "1990-12-31"),
    lambda: ra.analyze_asset("SPY", "2022-06-01", "2022-06-01"),  # one price -> not enough data
    lambda: ra.analyze_sector("Nope", *FULL),
    lambda: ra.correlation(["SPY"], *FULL),
    lambda: ra.stress_test_2022("NOPE"),
])
def test_errors_are_dicts(call):
    r = call()
    json.dumps(r, allow_nan=False)
    assert r["status"] == "error" and r["error"]


@has_data
def test_short_history_warns():
    r = ra.analyze_asset("SPY", "2022-01-01", "2022-03-31")
    assert any("< 252" in w for w in r["warnings"])


# ---------- no look-ahead ----------

@has_data
def test_future_data_does_not_change_results(monkeypatch):
    before = ok(ra.analyze_asset("SPY", "2022-01-01", "2022-06-30"))
    real = dr._load

    def with_future(n):
        df = real(n)
        if n != "prices_daily.csv":
            return df
        fut = df[df.ticker == "SPY"].tail(1).assign(date=pd.Timestamp("2022-07-05"), adj_close=1e9)
        return pd.concat([df, fut])
    monkeypatch.setattr(dr, "_load", with_future)
    assert ok(ra.analyze_asset("SPY", "2022-01-01", "2022-06-30")) == before


@has_data
def test_two_prices_is_not_enough():
    r = ra.analyze_asset("SPY", "2022-06-01", "2022-06-02")  # 2 trading days -> 1 return -> vol undefined
    json.dumps(r, allow_nan=False)
    assert r["status"] == "error"
