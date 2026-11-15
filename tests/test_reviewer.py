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
    return ok({"checks": checks, "members": members or [target], "overall": "flag"})


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


# ---------- regressions from the phase 1-3 review ----------

@pytest.mark.parametrize("text", [
    "NVDA volatility is 9% [fact: step 1]",            # small number with % must be checked
    "max drawdown only -5.0% [fact: step 1]",          # decimals / negatives are not bare counts
])
def test_small_numbers_are_checked(text):
    assert reviewer.check_answer(text, answer_trace())["verdict"] == "fail"


def two_step_trace():
    t = RunTrace("robert", "q", AS_OF)
    t.add("worker:risk_analyst", "analyze_asset", {"ticker": "NVDA"}, ok({"annualized_vol": 0.5112}))
    t.add("worker:risk_analyst", "analyze_asset", {"ticker": "XBB.TO"}, ok({"annualized_vol": 0.0661}))
    t.add("boss", "plan", None, {"note": "NVDA 77.7%"})
    return t


def test_number_must_come_from_cited_step():
    t = two_step_trace()
    assert reviewer.check_answer("NVDA vol 51.1% [fact: step 1]", t)["verdict"] == "pass"
    assert reviewer.check_answer("NVDA vol 51.1% [fact: step 2]", t)["verdict"] == "fail"  # wrong step
    assert reviewer.check_answer("NVDA vol 51.1% (no tag)", t)["verdict"] == "pass"         # any worker step


def test_citation_must_be_a_worker_step():
    v = reviewer.check_answer("NVDA 77.7% [fact: step 3]", two_step_trace())  # boss step is not evidence
    assert v["verdict"] == "fail" and any("not a worker or user step" in r for r in v["reasons"])


@has_data
def test_stress_test_alone_is_not_sector_analysis():
    t = full_trace()
    t.steps = [s for s in t.steps if not (s["action"] == "analyze_sector")]
    t.add("worker:risk_analyst", "stress_test_2022", {"tickers_or_sector": "Bonds"}, ok())
    assert any("'Bonds' is missing a successful analyze_sector" in r
               for r in reviewer.review_work(t, PLAN, "robert", Q, AS_OF)["reasons"])


@has_data
def test_all_esg_names_must_be_checked():
    t = full_trace("mateo")
    t.add("worker:suitability", "check_suitability", {"target": "XOM"}, suit("XOM", "mateo", ["XOM"]))
    reasons = reviewer.review_work(t, PLAN, "mateo", Q, AS_OF)["reasons"]
    assert any("['ENB.TO', 'CNQ.TO']" in r for r in reasons)


@has_data
def test_unexplained_error_fails_but_retry_or_note_passes():
    err = ("worker:risk_analyst", "analyze_asset", {"ticker": "AMD"}, {"status": "error", "error": "unknown"})
    t = full_trace(extra=[err])
    assert any("neither retried" in r for r in reviewer.review_work(t, PLAN, "robert", Q, AS_OF)["reasons"])
    noted = {**PLAN, "requested_targets": ["NVDA", "AMD"], "reasoning_notes": "AMD is not in the universe"}
    assert reviewer.review_work(t, noted, "robert", Q, AS_OF)["verdict"] == "pass"
    t2 = full_trace(extra=[("worker:risk_analyst", "analyze_sector", {"sector": "Nope"},
                            {"status": "error", "error": "unknown"}),
                           ("worker:risk_analyst", "analyze_sector", {"sector": "nope"}, ok())])
    assert reviewer.review_work(t2, PLAN, "robert", Q, AS_OF)["verdict"] == "pass"  # retried successfully


@has_data
@pytest.mark.parametrize("q,expected", [("Royal Bank or TD?", ["TD.TO"]), ("is nvda.", ["NVDA"])])
def test_extract_targets_more(q, expected):
    assert reviewer.extract_targets(q) == expected


@has_data
def test_recommended_sector_with_conflict_fails():
    t = full_trace()
    bonds = [s for s in t.steps if s["action"] == "check_suitability" and s["input"]["target"] == "Bonds"][0]
    bonds["output"]["data"]["overall"] = "conflict"
    assert any("suitability conflict" in r for r in reviewer.review_work(t, PLAN, "robert", Q, AS_OF)["reasons"])


# ---------- regressions from the verification pass ----------

def test_user_step_and_mixed_citation_forms():
    t = RunTrace("robert", "q", AS_OF)
    t.add("user", "question", None, {"persona_profile": {"limits": {"vol_max": 0.10}}})
    t.add("worker:risk_analyst", "analyze_asset", {"ticker": "NVDA"}, ok({"annualized_vol": 0.5112}))
    t.add("worker:risk_analyst", "analyze_asset", {"ticker": "XBB.TO"}, ok({"annualized_vol": 0.0661, "d": "2022-12-30"}))
    for text in ["NVDA 51.1% vs 10% limit [fact: step 1, step 2]",                 # user step is citable
                 "NVDA 51.1% [fact: step 2]. XBB.TO vol is 6.6%.",                    # untagged 2nd sentence
                 "NVDA 51.1% in the 2022 stress [fact: step 2]",                      # year from elsewhere
                 "phase mid, NVDA 51.1% [assumption, fact: step 2]",                  # combined tag
                 "| NVDA | 51.1% | [fact: step 2] |"]:                                # table row
        assert reviewer.check_answer(text, t)["verdict"] == "pass", text
    for text in ["XBB.TO 6.6% [assumption, fact: step 2]",                            # combined tag is scoped
                 "NVDA 9 % [fact: step 2]"]:                                          # "9 %" is checked
        assert reviewer.check_answer(text, t)["verdict"] == "fail", text


@has_data
def test_weighted_probe_conflict_does_not_block_sector():
    t = full_trace()
    t.add("worker:suitability", "check_suitability", {"target": "Bonds", "proposed_weight": 0.9},
          {**suit("Bonds"), "data": {**suit("Bonds")["data"], "overall": "conflict"}})
    assert reviewer.review_work(t, PLAN, "robert", Q, AS_OF)["verdict"] == "pass"  # unweighted check is "flag"


@has_data
def test_error_retried_with_corrected_name_or_explained():
    t = full_trace(extra=[("worker:risk_analyst", "analyze_sector", {"sector": "Tech"},
                           {"status": "error", "error": "unknown"})])
    plan = {**PLAN, "recommended_sectors": ["Bonds", "Information Technology"]}
    for action, key in (("analyze_sector", "sector"), ("sector_momentum", "sector_or_ticker"),
                        ("check_suitability", "target")):
        t.add(f"worker:{action}", action, {key: "Information Technology"},
              suit("Information Technology") if "suit" in action else ok())
    assert reviewer.review_work(t, plan, "robert", Q, AS_OF)["verdict"] == "pass"
    t2 = full_trace(extra=[("worker:risk_analyst", "correlation", {"tickers": ["NVDA", "AMD"]},
                            {"status": "error", "error": "unknown AMD"}),
                           ("worker:risk_analyst", "correlation", {"tickers": ["SPY", "TLT"]}, ok())])
    assert reviewer.review_work(t2, PLAN, "robert", Q, AS_OF)["verdict"] == "fail"   # unrelated success
    noted = {**PLAN, "reasoning_notes": "correlation of NVDA and AMD failed: AMD is not in the universe"}
    assert reviewer.review_work(t2, noted, "robert", Q, AS_OF)["verdict"] == "pass"


@has_data
def test_notes_match_whole_words():
    plan = {**PLAN, "requested_targets": ["NVDA", "AI"], "reasoning_notes": "the request fails the limits"}
    assert any("'AI'" in r for r in reviewer.review_work(full_trace(), plan, "robert", Q, AS_OF)["reasons"])


@pytest.mark.parametrize("text", ["NVDA vol is more than 5x the 10% limit [fact: step 1]",
                                  "about 7 × the limit [fact: step 1]", "7 times the limit [fact: step 1]"])
def test_calculated_multiples_are_checked(text):
    assert reviewer.check_answer(text, answer_trace())["verdict"] == "fail"


def test_counts_followed_by_words_still_exempt():
    assert reviewer.check_answer("3 asset classes and 2 extra notes [fact: step 1]", answer_trace())["verdict"] == "pass"


# ---------- semantic check (LLM call injected) ----------

def test_semantic_check_sends_only_cited_steps_and_formats_issues():
    t = two_step_trace()
    seen = {}

    def fake(system, user):
        seen["system"], seen["user"] = system, user
        return {"verdict": "fail", "issues": [{"quote": "NVDA vol 51.1% is within the limit",
                                               "problem": "51.1% is above 10%", "evidence": "vol_max flag"}]}
    v = reviewer.semantic_check("NVDA vol 51.1% is within the limit [fact: step 1]", t, call=fake)
    assert v["verdict"] == "fail" and "51.1% is above 10%" in v["reasons"][0]
    assert '"step": 1' in seen["user"] and '"step": 2' not in seen["user"]   # only the cited step
    assert "77.7" not in seen["user"]                                       # boss plan is never evidence
    assert "MEANING" in seen["system"]


def test_semantic_check_pass_and_fail_without_details():
    t = two_step_trace()
    assert reviewer.semantic_check("ok [fact: step 1]", t, call=lambda s, u: {"verdict": "pass", "issues": []})["verdict"] == "pass"
    v = reviewer.semantic_check("ok [fact: step 1]", t, call=lambda s, u: {"verdict": "fail", "issues": []})
    assert v["verdict"] == "fail" and v["reasons"]
