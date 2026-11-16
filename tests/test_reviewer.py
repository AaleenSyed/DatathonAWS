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


# ---------- no promises or predictions (guardrails/05_presenter.md) ----------

@pytest.mark.parametrize("text", [
    "NVDA will go up next year.", "Utilities are a safe bet for Robert.", "Returns are guaranteed.",
    "Bonds will rise in value.", "Ce secteur va monter.", "Un rendement garanti.", "Un placement sans risque.",
])
def test_predictions_fail(text):
    v = reviewer.check_answer(text, answer_trace())
    assert v["verdict"] == "fail" and "predicts returns" in " ".join(v["reasons"])


@pytest.mark.parametrize("text", [
    "Returns are not guaranteed.", "Past results do not guarantee future returns.",
    "Les rendements ne sont pas garantis.", "Aucun placement n’est sans risque.",
    "Historically, sectors like Utilities have tended to hold up better.",
])
def test_negated_or_historical_wording_passes(text):
    assert reviewer.check_answer(text, answer_trace())["verdict"] == "pass"


# ---------- comparisons must match the order of their numbers (eval: "17.0% vol lower than 15.7%") ----------

@pytest.mark.parametrize("text,lang", [
    # the eval finding, verbatim
    ("- Consumer Staples annualized volatility is 17.0%, lower than Financials' 15.7%, and its 2022 drawdown was "
     "-13.7%, within Robert's -15.0% limit. [fact: step 17, 18, 32]", "en"),
    ("Consumer Staples has the lowest volatility (17.0%), Financials 2nd (15.7%).", "en"),
    ("Consumer Staples (17.0%) has lower volatility than Financials (15.7%).", "en"),
    ("TLT (16.1%) is safer than XBB.TO (6.6%) on annualized volatility.", "en"),
    ("NVDA had a smaller 2022 drawdown (-59.2%) than Consumer Staples (-13.7%).", "en"),
    ("XBB.TO's volatility of 6.6% exceeds Mateo's 15.0% limit.", "en"),
    ("Financials has the best 12-month momentum (19.0%), Health Care 2nd (51.8%).", "en"),
    ("Consumer Staples affiche une volatilité de 17,0 %, inférieure à celle de Financials (15,7 %).", "fr"),
    ("Consumer Staples a la volatilité la plus faible (17,0 %), Financials 2e (15,7 %).", "fr"),
])
def test_wrong_comparison_fails(text, lang):
    assert reviewer.wrong_comparisons(text, lang), text
    v = reviewer.check_answer(text, answer_trace(), lang=lang)
    assert v["verdict"] == "fail" and any("comparisons contradict" in r and "compare_metrics" in r
                                          for r in v["reasons"])


@pytest.mark.parametrize("text,lang", [
    ("Utilities has the lowest annualized volatility among the sector groups analyzed (14.7%), Financials 2nd "
     "(15.7%), Consumer Staples 3rd (17.0%), Information Technology the highest (30.1%).", "en"),
    ("NVDA has a higher annualized volatility (51.1%) than Consumer Staples (17.0%).", "en"),
    ("NVDA has a deeper maximum drawdown (-63.5%) than Consumer Staples (-16.3%).", "en"),
    ("NVDA has a lower 2022 return (-46.9%) than Consumer Staples (8.4%).", "en"),
    ("Consumer Staples had a smaller 2022 drawdown (-13.7%) than Financials (-22.2%).", "en"),
    ("NVDA's 51.1% volatility exceeds Robert's 10.0% limit.", "en"),
    ("TLT reached -31.8% and XBB.TO -15.3% in 2022, both exceeding the -15.0% limit.", "en"),  # drawdown limit
    ("Utilities fell -7.9% (maximum drawdown -24.0%), far less severe than AAPL's -21.4%.", "en"),
    ("Bonds members range from very low volatility (ZST.TO at 0.6%) to higher risk (TLT at 16.1%).", "en"),
    ("Volatility 14.7% is within Mateo's 15.0% limit, and it trades above its 200-day average with 12-month "
     "momentum of 18.4%.", "en"),
    ("Keep at most 15.0% in crypto; anything above the 15.0% cap is a conflict.", "en"),
    ("Utilities affiche une volatilité de 14,7 %, la plus basse des secteurs analysés, et une baisse maximale "
     "de -24,0 %.", "fr"),
    ("En 2022, le secteur a reculé de 43,9 % au pire point, soit moins que les -59,2 % de NVDA.", "fr"),
    ("If the weight were 20.0%, it would be higher than the 15.0% cap. [scenario]", "en"),
])
def test_correct_or_unclear_comparison_passes(text, lang):
    assert reviewer.wrong_comparisons(text, lang) == [], text


# ---------- suitability statuses copied exactly (eval: pass relabeled as info) ----------

def status_trace():
    """Robert: Bonds (bonds/cash minimum pass, volatility flag because of TLT), Consumer Staples (volatility flag,
    bonds/cash minimum info, 2022 drawdown pass)."""
    t = RunTrace("robert", "q", AS_OF)

    def check(rule, status, value=None, limit=None):
        return {"rule": rule, "status": status, "value": value, "limit": limit, "explanation": ""}
    t.add("worker:suitability", "check_suitability", {"target": "Bonds"}, ok({
        "target": "Bonds", "members": ["XBB.TO", "TLT"], "overall": "flag", "checks": [
            check("crypto_max", "pass", 0.0, 0.0),
            check("vol_max", "flag", {"XBB.TO": 0.066, "TLT": 0.161}, 0.10),
            check("bonds_cash_min", "pass", None, 0.5),
            check("stress_2022_max_drawdown", "flag", {"XBB.TO": -0.153, "TLT": -0.318}, -0.15)]}))
    t.add("worker:suitability", "check_suitability", {"target": "Consumer Staples"}, ok({
        "target": "Consumer Staples", "members": ["ATD.TO", "PG"], "overall": "flag", "checks": [
            check("crypto_max", "pass", 0.0, 0.0),
            check("vol_max", "flag", {"Consumer Staples": 0.170}, 0.10),
            check("bonds_cash_min", "info", None, 0.5),
            check("stress_2022_max_drawdown", "pass", {"Consumer Staples": -0.137}, -0.15)]}))
    return t


@pytest.mark.parametrize("text", [
    # eval b0003: Bonds counting toward the minimum is a pass, not info
    "- **Info — bonds/cash minimum**: Bonds counts toward the required 50.0% bonds/cash minimum. [fact: step 1]",
    # eval b0010 (French): Bonds is flag / pass, never "information"
    "- Bonds — **information** : le portefeuille doit comporter au moins 50,0 % en obligations et encaisse ; "
    "Bonds compte dans ce minimum. [fact: step 1]",
    "- Consumer Staples: volatility info, 17.0% vs 10.0%.",                        # uncited: nearest target
    "- **Pass — volatility**: TLT at 16.1% vs the 10.0% limit. [fact: step 1]",   # member TLT is above the limit
    "- Consumer Staples: 2022 drawdown flag, -13.7% vs -15.0% [fact: step 2]",
    "- **Conflict** — Consumer Staples: 17.0% volatility vs Robert's 10.0% limit. [fact: step 2]",
])
def test_relabeled_status_fails(text):
    assert reviewer.wrong_statuses(text, status_trace()), text


@pytest.mark.parametrize("text", [
    "- **Pass — bonds/cash minimum**: Bonds counts toward the required 50.0% bonds/cash minimum. [fact: step 1]",
    "- **Flag — volatility**: TLT at 16.1% exceeds Robert's 10.0% limit. [fact: step 1]",
    "- XBB.TO passes the volatility limit at 6.6%. [fact: step 1]",                 # member within the limit
    "- **Info — bonds/cash minimum**: the portfolio still needs at least 50.0% in bonds/cash alongside "
    "Consumer Staples. [fact: step 2]",
    "- Consumer Staples: volatility flag, 17.0% vs 10.0% [fact: step 2]; bonds/cash minimum still needed, info, "
    "50.0% [fact: step 2]; 2022 drawdown pass, -13.7% within -15.0% [fact: step 2].",
    "- Consumer Staples: crypto 0% (pass), volatility 17.0% vs 10.0% limit (flag), bonds/cash minimum (info) "
    "[fact: step 2].",
    "- Signalement — Consumer Staples : volatilité de 17,0 % vs limite de 10,0 %. [fact: step 2]",
    "NVDA conflicts with Robert's profile.",                                      # verb, not the status
    "Bonds has zero conflicts and no ESG flags. [fact: step 1]",                   # negated
    "Historically, sectors like Information Technology have tended to do well. [assumption]",  # part of a name
    "At a 60.0% weight, Consumer Staples would be a conflict. [fact: step 2] [scenario]",
])
def test_status_copied_or_not_a_status_passes(text):
    assert reviewer.wrong_statuses(text, status_trace()) == [], text


def test_check_answer_reports_relabeled_status():
    v = reviewer.check_answer("- **Info — bonds/cash minimum**: Bonds counts toward the 50.0% bonds/cash "
                              "minimum. [fact: step 1]", status_trace())
    assert v["verdict"] == "fail"
    assert any("statuses differ from the trace" in r and "'Info'" in r and "pass" in r for r in v["reasons"])
