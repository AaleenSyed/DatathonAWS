import json

import pandas as pd
import pytest

from workers import data_retriever as dr

pytestmark = pytest.mark.skipif(not (dr.DATA_DIR / "prices_daily.csv").exists(), reason="starter data not in data/")


def raw(name):
    return dr._load(name)


def json_safe(res):
    json.dumps(res, allow_nan=False)
    return res


@pytest.fixture
def patched_load(monkeypatch):
    """Patch dr._load so a test can modify one file's DataFrame."""
    real = dr._load

    def patch(name, fn):
        monkeypatch.setattr(dr, "_load", lambda n: fn(real(n).copy()) if n == name else real(n))
    return patch


# ---------- normal cases ----------

def test_spy_2022_period_matches_rows():
    r = json_safe(dr.get_prices("SPY", "2022-01-01", "2022-12-31", currency="USD"))
    assert r["status"] == "ok" and r["currency"] == "USD"
    p = raw("prices_daily.csv")
    spy = p[(p.ticker == "SPY") & (p.date >= "2022-01-01") & (p.date <= "2022-12-31")]
    assert r["period"] == {"start": spy.date.min().strftime("%Y-%m-%d"), "end": spy.date.max().strftime("%Y-%m-%d")}
    assert len(r["data"]["SPY"]) == len(spy)
    assert "Yahoo" in r["source"]


def test_usd_to_cad_hand_check():
    p, fx = raw("prices_daily.csv"), raw("fx_usdcad_daily.csv")
    d = pd.Timestamp("2023-06-15")
    usd = p[(p.ticker == "AAPL") & (p.date == d)].adj_close.iloc[0]
    rate = fx[fx.date <= d].sort_values("date").usdcad.iloc[-1]
    r = dr.get_prices("AAPL", "2023-06-15", "2023-06-15")
    assert r["data"]["AAPL"][0]["adj_close"] == pytest.approx(usd * rate)


def test_fx_gap_uses_previous_rate():
    p, fx = raw("prices_daily.csv"), raw("fx_usdcad_daily.csv")
    us_days = set(p[p.ticker == "AAPL"].date)
    gap = sorted(us_days - set(fx.date))[0]  # a U.S. trading day with no Bank of Canada rate
    prev = fx[fx.date < gap].sort_values("date").iloc[-1]
    usd = p[(p.ticker == "AAPL") & (p.date == gap)].adj_close.iloc[0]
    d = gap.strftime("%Y-%m-%d")
    r = dr.get_prices("AAPL", d, d)
    assert r["data"]["AAPL"][0]["adj_close"] == pytest.approx(usd * prev.usdcad)


def test_crypto_has_weekend_rows():
    r = dr.get_prices("BTC-USD", "2023-01-01", "2023-01-31")
    days = [pd.Timestamp(x["date"]).day_of_week for x in r["data"]["BTC-USD"]]
    assert 5 in days and 6 in days and len(days) == 31


def test_cad_ticker_not_converted_in_cad():
    p = raw("prices_daily.csv")
    v = p[(p.ticker == "RY.TO") & (p.date == "2023-06-15")].adj_close.iloc[0]
    r = dr.get_prices(["RY.TO", "AAPL"], "2023-06-15", "2023-06-15")
    assert r["data"]["RY.TO"][0]["adj_close"] == pytest.approx(v) and set(r["data"]) == {"RY.TO", "AAPL"}


def test_universe_and_asset_info():
    assert len(json_safe(dr.get_universe())["data"]) == len(raw("assets_universe.csv"))
    assert json_safe(dr.get_asset_info("NVDA"))["data"]["sector"] == "Information Technology"


# ---------- edge cases / errors ----------

@pytest.mark.parametrize("call", [
    lambda: dr.get_prices("NOPE", "2022-01-01", "2022-12-31"),
    lambda: dr.get_prices("SPY", "2022-12-31", "2022-01-01"),
    lambda: dr.get_prices("SPY", "1990-01-01", "1990-12-31"),
    lambda: dr.get_prices([], "2022-01-01", "2022-12-31"),
    lambda: dr.get_prices("SPY", "2022-01-01", "2022-12-31", currency="EUR"),
    lambda: dr.get_prices("SPY", "not a date", "2022-12-31"),
    lambda: dr.get_asset_info("NOPE"),
    lambda: dr.get_fx("2022-12-31", "2022-01-01"),
    lambda: dr.get_macro("NOPE", "2022-01-01", "2022-12-31"),
])
def test_bad_input_returns_error_dict(call):
    r = json_safe(call())
    assert r["status"] == "error" and r["error"]


def test_unknown_ticker_in_list_is_warning():
    r = dr.get_prices(["SPY", "NOPE"], "2022-01-01", "2022-01-31")
    assert r["status"] == "ok" and list(r["data"]) == ["SPY"] and any("NOPE" in w for w in r["warnings"])


# ---------- no look-ahead ----------

def test_no_dates_after_end(patched_load):
    def add_future(df):
        fut = df[df.ticker == "SPY"].tail(1).assign(date=pd.Timestamp("2022-07-01"), adj_close=1e9)
        return pd.concat([df, fut])
    patched_load("prices_daily.csv", add_future)
    r = dr.get_prices("SPY", "2022-01-01", "2022-06-30")
    assert max(x["date"] for x in r["data"]["SPY"]) <= "2022-06-30"


def test_macro_only_published_values():
    r = json_safe(dr.get_macro("CPIAUCSL", "2025-01-01", "2026-11-12", as_of="2026-11-12"))
    rows = r["data"]["CPIAUCSL"]
    assert all(x["available_date"] <= "2026-11-12" for x in rows)
    m = raw("macro_rates.csv")
    last_ref = m[m.series_id == "CPIAUCSL"].date.max()
    # the latest reference month is not yet published 3 weeks after its month end
    if last_ref + pd.offsets.MonthEnd(0) + pd.Timedelta(days=21) > pd.Timestamp("2026-11-12"):
        assert rows[-1]["date"] < last_ref.strftime("%Y-%m-%d")


def test_macro_daily_series_dated_same_day():
    r = dr.get_macro("DGS10", "2022-01-01", "2022-01-31")
    assert all(x["date"] == x["available_date"] for x in r["data"]["DGS10"]) and r["units"]["DGS10"]


def test_fx_ok():
    r = json_safe(dr.get_fx("2022-01-01", "2022-01-31"))
    assert r["status"] == "ok" and all(1 < x["usdcad"] < 2 for x in r["data"])
