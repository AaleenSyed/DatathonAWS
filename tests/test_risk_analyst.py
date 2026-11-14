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


# ---------- AUM-weighted basket with stubbed data ----------

@pytest.fixture
def two_etf_sector(monkeypatch):
    dates = pd.date_range("2024-01-01", periods=4).strftime("%Y-%m-%d")
    a, b = [100, 102, 101, 104], [50, 49, 50, 51]
    monkeypatch.setattr(dr, "get_universe", lambda: {"status": "ok", "data": [
        {"ticker": "A", "asset_class": "etf_bond", "sector": "Test (a)"},
        {"ticker": "B", "asset_class": "etf_bond", "sector": "Test (b)"}]})
    monkeypatch.setattr(dr, "get_prices", lambda t, s, e, c="CAD": {
        "status": "ok", "source": "stub", "warnings": [], "currency": c,
        "data": {"A": [{"date": d, "adj_close": v} for d, v in zip(dates, a)],
                 "B": [{"date": d, "adj_close": v} for d, v in zip(dates, b)]}})
    return a, b


def test_aum_weighted_basket(monkeypatch, two_etf_sector):
    a, b = two_etf_sector
    monkeypatch.setattr(dr, "get_fund_weights", lambda t: {
        "status": "ok", "source": "stub AUM", "warnings": [],
        "data": {"weights": {"A": 0.75, "B": 0.25}, "retrieved_date": "2026-11-14"}})
    d = ok(ra.analyze_sector("Test", "2024-01-01", "2024-01-04"))
    idx = 1.0
    for i in range(1, 4):
        idx *= 1 + 0.75 * (a[i] / a[i - 1] - 1) + 0.25 * (b[i] / b[i - 1] - 1)
    assert d["total_return"] == pytest.approx(idx - 1)
    assert d["weighting"] == "fund size (AUM)" and sum(d["weights"].values()) == pytest.approx(1)


def test_aum_missing_falls_back_to_equal(monkeypatch, two_etf_sector):
    monkeypatch.setattr(dr, "get_fund_weights", lambda t: {
        "status": "ok", "source": "stub", "warnings": ["B: no AUM"],
        "data": {"weights": {"A": 1.0}, "retrieved_date": "2026-11-14"}})
    r = ra.analyze_sector("Test", "2024-01-01", "2024-01-04")
    assert r["data"]["weights"] == {"A": 0.5, "B": 0.5}
    assert any("fell back to equal weight" in w for w in r["warnings"])


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
    assert ok(ra.analyze_sector("Crypto asset", *FULL))["days_per_year"] == 365


@has_data
@pytest.mark.parametrize("sector,n", [("Bonds", 4), ("Broad market", 4), ("Information Technology", 5),
                                      ("Bonds (U.S. long Treasury)", 1)])
def test_sector_weights_sum_to_one(sector, n):
    d = ok(ra.analyze_sector(sector, *FULL))
    assert len(d["members"]) == n and sum(d["weights"].values()) == pytest.approx(1)


@has_data
def test_bonds_basket_uses_aum_when_available():
    d = ok(ra.analyze_sector("Bonds", *FULL))
    expected = "fund size (AUM)" if (dr.DATA_DIR / "fund_aum.csv").exists() else "equal weight"
    assert d["weighting"] == expected


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
