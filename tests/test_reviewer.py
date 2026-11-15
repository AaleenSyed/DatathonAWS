import pytest

import reviewer
from run_trace import RunTrace
from workers import data_retriever as dr

has_data = pytest.mark.skipif(not (dr.DATA_DIR / "prices_daily.csv").exists(), reason="starter data not in data/")
AS_OF = "2026-11-12"


def ok(data=None, end=AS_OF, source="src"):
    return {"status": "ok", "data": data or {}, "source": source, "period": {"start": "2021-11-12", "end": end},
            "currency": "CAD", "warnings": []}


def suit(target, persona="robert", members=None):
    from personas import PERSONAS
    checks = [{"rule": r} for r in PERSONAS[persona]["limits"]]
    return ok({"checks": checks, "members": members or [target]})


def full_trace(persona="robert", extra=()):
    """Trace where NVDA was requested and Bonds recommended, everything done."""
    t = RunTrace(persona, "q", AS_OF)
    t.add("worker:market_context", "cycle_phase", {"as_of": AS_OF}, ok({"phase": "Mid cycle"}))
    t.add("worker:risk_analyst", "analyze_asset", {"ticker": "NVDA"}, ok({"annualized_vol": 0.5112}))
    t.add("worker:suitability", "check_suitability", {"target": "NVDA"}, suit("NVDA", persona))
    for action, key in (("analyze_sector", "sector"), ("sector_momentum", "sector_or_ticker"),
                        ("check_suitability", "target")):
        t.add(f"worker:{action}", action, {key: "Bonds"}, suit("Bonds", persona) if "suit" in action else ok())
    for args in extra:
        t.add(*args)
    return t


PLAN = {"requested_targets": ["NVDA"], "recommended_sectors": ["Bonds"]}
Q = "Should Robert buy NVDA?"


# ---------- target extraction ----------

@has_data
@pytest.mark.parametrize("q,expected", [
    ("I want to put a big part of my savings in NVDA, good idea?", ["NVDA"]),
    ("I only want AI and crypto, which industry should I focus on?", ["Crypto asset"]),
    ("Which industry gives balanced growth for me?", []),
    ("where should I shop?", []),                      # English word, not the ticker SHOP
    ("what about SHOP and Shopify", ["SHOP.TO"]),
    ("Is tech too risky? Apple vs Bitcoin", ["AAPL", "BTC-USD", "Information Technology"]),
])
def test_extract_targets(q, expected):
    assert reviewer.extract_targets(q) == expected


# ---------- review_work ----------

@has_data
def test_complete_work_passes():
    assert reviewer.review_work(full_trace(), PLAN, "robert", Q, AS_OF) == {"verdict": "pass", "reasons": []}


@has_data
def test_missing_suitability_for_requested_target_fails():
    t = full_trace()
    t.steps = [s for s in t.steps if not (s["action"] == "check_suitability" and s["input"]["target"] == "NVDA")]
    v = reviewer.review_work(t, PLAN, "robert", Q, AS_OF)
    assert v["verdict"] == "fail" and any("'NVDA' has no successful check_suitability" in r for r in v["reasons"])


@has_data
def test_failed_worker_does_not_count():
    t = full_trace()
    t.steps[1]["output"] = {"status": "error", "error": "boom"}
    v = reviewer.review_work(t, PLAN, "robert", Q, AS_OF)
    assert any("'NVDA' has no successful risk analysis" in r for r in v["reasons"])


@has_data
@pytest.mark.parametrize("plan,needle", [
    ({"requested_targets": ["NVDA"], "recommended_sectors": []}, "no recommended_sectors"),
    ({"requested_targets": ["NVDA"], "recommended_sectors": ["Utilities"]}, "'Utilities' is missing"),
    ({"requested_targets": ["NVDA"], "recommended_sectors": ["Space Mining"]}, "not a sector group"),
    ({"requested_targets": ["Information Technology (AI)"], "recommended_sectors": ["Bonds"]}, "not an exact"),
])
def test_plan_problems_fail(plan, needle):
    v = reviewer.review_work(full_trace(), plan, "robert", Q, AS_OF)
    assert v["verdict"] == "fail" and any(needle in r for r in v["reasons"])


@has_data
def test_missing_cycle_phase_fails():
    t = full_trace()
    t.steps = [s for s in t.steps if s["action"] != "cycle_phase"]
    assert any("cycle_phase" in r for r in reviewer.review_work(t, PLAN, "robert", Q, AS_OF)["reasons"])


@has_data
def test_missing_source_or_future_data_fails():
    t = full_trace(extra=[("worker:risk_analyst", "analyze_asset", {"ticker": "SPY"}, ok(source="")),
                          ("worker:risk_analyst", "analyze_asset", {"ticker": "QQQ"}, ok(end="2027-01-01"))])
    reasons = reviewer.review_work(t, PLAN, "robert", Q, AS_OF)["reasons"]
    assert any("has no source" in r for r in reasons) and any("after analysis date" in r for r in reasons)


@has_data
def test_missing_persona_limit_fails():
    t = full_trace()
    t.steps[2]["output"]["data"]["checks"] = t.steps[2]["output"]["data"]["checks"][:1]
    assert any("did not evaluate persona limits" in r for r in reviewer.review_work(t, PLAN, "robert", Q, AS_OF)["reasons"])


@has_data
def test_mateo_requires_esg_check():
    t = full_trace("mateo")
    v = reviewer.review_work(t, PLAN, "mateo", Q, AS_OF)
    assert any("ESG-review names" in r and "Energy" in r for r in v["reasons"])
    t.add("worker:suitability", "check_suitability", {"target": "Energy"},
          suit("Energy", "mateo", ["ENB.TO", "CNQ.TO", "XOM"]))
    assert reviewer.review_work(t, PLAN, "mateo", Q, AS_OF)["verdict"] == "pass"


# ---------- check_answer ----------

def answer_trace():
    t = RunTrace("robert", "q", AS_OF)
    t.add("worker:risk_analyst", "analyze_asset", {"ticker": "NVDA"},
          ok({"annualized_vol": 0.51116, "max_drawdown": -0.6352, "name": "iShares S&P/TSX 60 Index ETF"}))
    return t


@pytest.mark.parametrize("text", [
    "NVDA vol is 51.1% [fact: step 1]",
    "NVDA vol is about 51% [fact: step 1]",
    "max drawdown −63.5% [fact: step 1]",
    "max drawdown of 63.52% [fact: step 1]",
    "the TSX 60 ETF, 3 asset classes, 12 months [fact: step 1]",
    "window 2021-11-12 to 2026-11-12",
])
def test_supported_numbers_pass(text):
    assert reviewer.check_answer(text, answer_trace())["verdict"] == "pass"


@pytest.mark.parametrize("text,needle", [
    ("NVDA vol is 42.0% [fact: step 1]", "42.0"),
    ("NVDA vol is 51.3% [fact: step 1]", "51.3"),  # wrong rounding
    ("returned 1,234% [fact: step 1]", "1,234"),
    ("NVDA vol is 51.1% [fact: step 9]", "step 9"),
])
def test_unsupported_numbers_or_citations_fail(text, needle):
    v = reviewer.check_answer(text, answer_trace())
    assert v["verdict"] == "fail" and needle in " ".join(v["reasons"])
