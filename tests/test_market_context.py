import pandas as pd
import pytest

from conftest import assert_plain
from workers import data_retriever as dr
from workers import market_context as mc

has_data = pytest.mark.skipif(not (dr.DATA_DIR / "macro_extra.csv").exists(),
                              reason="data/macro_extra.csv not fetched (run data/fetch_fred_extra.py)")
AS_OF = pd.Timestamp("2025-06-30")


def months_ago(n):
    return (AS_OF - pd.DateOffset(months=n)).strftime("%Y-%m-%d")


@pytest.fixture
def macro(monkeypatch):
    """Stub get_macro with {sid: [(date, value), ...]}; values are treated as already published."""
    calls = []

    def setup(series):
        def fake(ids, start, end, as_of=None):
            calls.append(as_of)
            data = {s: [{"date": d, "available_date": d, "value": v} for d, v in rows if d <= as_of]
                    for s, rows in series.items() if s in ids}
            data = {s: r for s, r in data.items() if r}
            if not data:
                return {"status": "error", "error": "no data"}
            return {"status": "ok", "data": data, "source": "stub", "period": {"start": start, "end": end},
                    "currency": None, "warnings": [], "units": {s: "u" for s in data}}
        monkeypatch.setattr(dr, "get_macro", fake)
        return calls
    return setup


def calm(**over):
    """Neutral signals: no recession, curve positive, INDPRO flat-to-rising."""
    s = {"SAHMREALTIME": [(months_ago(i), 0.1) for i in range(12, 0, -1)],
         "RECPROUSM156N": [(months_ago(i), 1.0) for i in range(12, 0, -1)],
         "T10Y2Y": [(months_ago(i), 0.5) for i in range(14, -1, -1)],
         "INDPRO": [(months_ago(i), 100.0 + (12 - i) * 0.1) for i in range(12, 0, -1)]}
    s.update(over)
    return s


# ---------- cycle rules (stubbed signals) ----------

def test_mid_cycle_when_nothing_fires(macro):
    calls = macro(calm())
    d = assert_plain(mc.cycle_phase(AS_OF.strftime("%Y-%m-%d")))["data"]
    assert d["phase"] == "Mid cycle" and d["claim_type"] == "assumption"
    assert d["sector_tilt"] == mc.CYCLE_TILT["Mid cycle"] and "not a prediction" in d["statement"]
    assert calls == ["2025-06-30"]  # as_of is passed to get_macro (publication filter)


@pytest.mark.parametrize("sahm,recpro,phase", [
    (0.5, 1.0, "Recession risk"),    # boundary: >= 0.5
    (0.49, 1.0, "Mid cycle"),
    (0.1, 30.0, "Recession risk"),   # boundary: >= 30
    (0.1, 29.9, "Mid cycle"),
])
def test_recession_thresholds(macro, sahm, recpro, phase):
    s = calm()
    s["SAHMREALTIME"][-1] = (s["SAHMREALTIME"][-1][0], sahm)
    s["RECPROUSM156N"][-1] = (s["RECPROUSM156N"][-1][0], recpro)
    macro(s)
    assert mc.cycle_phase(AS_OF.strftime("%Y-%m-%d"))["data"]["phase"] == phase


def test_early_cycle_after_recent_signal_with_rising_indpro(macro):
    s = calm()
    s["SAHMREALTIME"][4] = (s["SAHMREALTIME"][4][0], 0.7)  # 8 months ago
    macro(s)
    d = mc.cycle_phase(AS_OF.strftime("%Y-%m-%d"))["data"]
    assert d["phase"] == "Early cycle" and d["flags"]["recession_signal_past_12m"] and d["flags"]["indpro_rising"]


def test_no_early_cycle_when_indpro_falling(macro):
    s = calm(INDPRO=[(months_ago(i), 100.0 - (12 - i) * 0.1) for i in range(12, 0, -1)])
    s["SAHMREALTIME"][4] = (s["SAHMREALTIME"][4][0], 0.7)
    macro(s)
    assert mc.cycle_phase(AS_OF.strftime("%Y-%m-%d"))["data"]["phase"] == "Mid cycle"


@pytest.mark.parametrize("inverted_months_ago,phase", [(0, "Late cycle"), (6, "Late cycle"), (13, "Mid cycle")])
def test_late_cycle_inversion_window(macro, inverted_months_ago, phase):
    s = calm()
    s["T10Y2Y"] = [(d, -0.2 if d == months_ago(inverted_months_ago) else 0.5) for d, _ in s["T10Y2Y"]]
    macro(s)
    assert mc.cycle_phase(AS_OF.strftime("%Y-%m-%d"))["data"]["phase"] == phase


def test_recession_beats_inversion(macro):
    s = calm()
    s["T10Y2Y"][-1] = (s["T10Y2Y"][-1][0], -0.3)
    s["SAHMREALTIME"][-1] = (s["SAHMREALTIME"][-1][0], 0.8)
    macro(s)
    assert mc.cycle_phase(AS_OF.strftime("%Y-%m-%d"))["data"]["phase"] == "Recession risk"


def test_missing_series_warns(macro):
    s = calm()
    del s["T10Y2Y"]
    macro(s)
    r = mc.cycle_phase(AS_OF.strftime("%Y-%m-%d"))
    assert r["status"] == "ok" and any("T10Y2Y" in w for w in r["warnings"])


# ---------- fear vs hope ----------

@pytest.mark.parametrize("vix,mood", [(14.9, "calm/hope"), (15.0, "normal"), (25.0, "normal"), (25.1, "fear")])
def test_vix_thresholds(vix, mood):
    assert mc.vix_mood(vix) == mood


def test_credit_spread_rising_is_stress(macro):
    macro({"VIXCLS": [(months_ago(0), 30.0)],
           "BAMLH0A0HYM2": [(months_ago(4), 3.0), (months_ago(3), 3.2), (months_ago(0), 4.0)]})
    d = assert_plain(mc.fear_hope(AS_OF.strftime("%Y-%m-%d")))["data"]
    assert d["mood"] == "fear" and d["credit_spread"]["rising_stress"]
    assert d["credit_spread"]["change_3m"] == pytest.approx(4.0 - 3.2)


def test_credit_spread_missing_is_reported(macro):
    macro({"VIXCLS": [(months_ago(0), 12.0)]})
    r = mc.fear_hope(AS_OF.strftime("%Y-%m-%d"))
    assert r["data"]["credit_spread"] is None and r["data"]["mood"] == "calm/hope"
    assert any("credit spread not available" in w for w in r["warnings"])


# ---------- trend metrics (hand check) ----------

def test_trend_metrics_hand_check():
    idx = pd.date_range("2024-01-01", periods=500, freq="D")
    p = pd.Series([100 * 1.001 ** i for i in range(500)], index=idx)
    bench = pd.Series(50.0, index=idx)
    a = idx[-1]
    d = mc.trend_metrics(p, bench, a)
    n6 = (a - (a - pd.DateOffset(months=6))).days
    n12 = (a - (a - pd.DateOffset(months=12))).days
    assert d["momentum_6m"] == pytest.approx(1.001 ** n6 - 1)
    assert d["momentum_12m"] == pytest.approx(1.001 ** n12 - 1)
    assert d["relative_strength_12m"] == pytest.approx(d["momentum_12m"])  # flat benchmark
    sma = sum(100 * 1.001 ** i for i in range(300, 500)) / 200
    assert d["price_vs_200d_avg"] == pytest.approx(p.iloc[-1] / sma - 1)
    assert d["trend"] == "above 200-day average" and d["drawdown_from_12m_high"] == 0


def test_trend_metrics_short_history():
    idx = pd.date_range("2024-01-01", periods=30, freq="D")
    d = mc.trend_metrics(pd.Series(range(1, 31), index=idx, dtype=float), pd.Series(1.0, index=idx), idx[-1])
    assert d["momentum_6m"] is None and d["price_vs_200d_avg"] is None


# ---------- real data ----------

@has_data
def test_real_cycle_uses_only_published_values():
    d = assert_plain(mc.cycle_phase("2026-11-12"))["data"]
    assert d["phase"] in mc.CYCLE_TILT
    assert all(s["available_date"] <= "2026-11-12" for s in d["signals"].values())


@has_data
def test_real_fear_hope():
    d = assert_plain(mc.fear_hope("2026-11-12"))["data"]
    assert d["vix"]["value"] > 0 and d["mood"] in ("calm/hope", "normal", "fear")


@has_data
def test_credit_spread_unavailable_early_in_window():
    assert mc.fear_hope("2022-06-30")["data"]["credit_spread"] is None


def test_real_momentum_industry_and_building_block():
    it = assert_plain(mc.sector_momentum("Information Technology", "2026-11-12"))["data"]
    assert it["kind"] == "industry" and "basket" in it and it["members"]["SHOP.TO"]["benchmark"] == "XIU.TO"
    bonds = assert_plain(mc.sector_momentum("Bonds", "2026-11-12"))["data"]
    assert bonds["kind"] == "building_block" and "basket" not in bonds
    assert assert_plain(mc.sector_momentum("NVDA", "2026-11-12"))["data"]["members"]["NVDA"]["benchmark"] == "SPY"


def test_momentum_errors():
    assert mc.sector_momentum("NOPE", "2026-11-12")["status"] == "error"
    assert mc.sector_momentum("SPY", "1990-01-01")["status"] == "error"


def test_momentum_no_look_ahead(monkeypatch):
    before = mc.sector_momentum("NVDA", "2024-06-28")
    real = dr._load

    def with_future(n):
        df = real(n)
        if n != "prices_daily.csv":
            return df
        return pd.concat([df, df[df.ticker == "NVDA"].tail(1).assign(date=pd.Timestamp("2024-07-01"), adj_close=1e9)])
    monkeypatch.setattr(dr, "_load", with_future)
    assert mc.sector_momentum("NVDA", "2024-06-28") == before


def test_cycle_phase_no_look_ahead(monkeypatch):
    """guardrails/03_workers_market_context.md: values dated after the analysis date, or monthly values not yet
    published by then (reference month + publication lag), must not change the phase or its signals."""
    as_of = "2026-11-12"
    before = mc.cycle_phase(as_of)
    real = dr._load

    def with_future(n):
        df = real(n)
        if n not in ("macro_extra.csv", "macro_rates.csv"):
            return df
        last = df.sort_values("date").groupby("series_id").tail(1)
        # extreme values: a recession signal and a deep inversion, dated after as_of and in as_of's own month
        # (a monthly value for November is only published in December)
        extreme = {"SAHMREALTIME": 5.0, "RECPROUSM156N": 99.0, "T10Y2Y": -3.0, "INDPRO": 1.0, "VIXCLS": 80.0}
        last = last.assign(value=last["series_id"].map(extreme).fillna(1e6))
        monthly = last[last["frequency"].str.contains("monthly", case=False)]
        rows = [monthly.assign(date=pd.Timestamp("2026-11-01"))]  # same month as as_of: not published yet
        rows += [last.assign(date=pd.Timestamp(d)) for d in ("2026-11-13", "2027-01-15")]  # after as_of
        return pd.concat([df, *rows], ignore_index=True)
    monkeypatch.setattr(dr, "_load", with_future)
    after = mc.cycle_phase(as_of)
    assert after["status"] == "ok" and after["data"]["phase"] == before["data"]["phase"]
    assert after["data"]["signals"] == before["data"]["signals"] and after["period"] == before["period"]
