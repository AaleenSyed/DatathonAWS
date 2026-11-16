"""Comparison facts (comparisons.py) and the presenter prompt rules that go with them. Synthetic traces: no
starter data, no Bedrock."""
import comparisons
import presenter
import reviewer
from personas import PERSONAS
from run_trace import RunTrace

AS_OF = "2026-11-12"


def ok(data):
    return {"status": "ok", "data": data, "source": "src", "period": {"start": "2021-11-12", "end": AS_OF},
            "currency": "CAD", "warnings": []}


def industry(name, vol, mdd, ret=1.0):
    return ("worker:risk_analyst", "analyze_sector", {"sector": name},
            ok({"sector": name, "kind": "industry", "annualized_vol": vol, "max_drawdown": mdd, "total_return": ret}))


def trace_with(*steps):
    t = RunTrace("Robert", "q", AS_OF)
    for s in steps:
        t.add(*s)
    return t


def eval_trace():
    """The sectors of the eval error: Consumer Staples 17.0% vs Financials 15.7% volatility."""
    return trace_with(
        industry("Consumer Staples", 0.17025, -0.1631, 0.667),
        industry("Financials", 0.15748, -0.2223, 1.775),
        industry("Utilities", 0.14714, -0.2401, 0.819),
        ("worker:risk_analyst", "analyze_asset", {"ticker": "NVDA"},
         ok({"ticker": "NVDA", "annualized_vol": 0.5113, "max_drawdown": -0.6346, "total_return": 5.2314})),
        ("worker:risk_analyst", "stress_test_2022", {"tickers_or_sector": "Consumer Staples"},
         ok({"Consumer Staples": {"total_return": 0.0840, "max_drawdown": -0.1372}})),
        ("worker:risk_analyst", "stress_test_2022", {"tickers_or_sector": "Financials"},
         ok({"Financials": {"total_return": -0.0140, "max_drawdown": -0.2223}})),
    )


PLAN = {"requested_targets": ["NVDA"], "recommended_sectors": ["Consumer Staples"]}


def facts(trace, plan=PLAN):
    out = comparisons.build(trace, plan, as_of=AS_OF)
    assert out["status"] == "ok", out
    return out["data"]


def ranking(data, metric, among="sector groups"):
    return next(r for r in data["rankings"] if r["metric"] == metric and r["among"] == among)


def test_volatility_ranking_puts_the_lowest_first():
    r = ranking(facts(eval_trace()), "annualized volatility")
    assert [(o["rank"], o["name"], o["value"]) for o in r["order"]] == [
        (1, "Utilities", "14.7%"), (2, "Financials", "15.7%"), (3, "Consumer Staples", "17.0%")]
    assert r["sentence"] == ("Utilities has the lowest annualized volatility among the sector groups analyzed (14.7%), "
                             "Financials 2nd (15.7%), Consumer Staples the highest (17.0%).")
    assert r["steps"] == [1, 2, 3]


def test_drawdown_ranking_smallest_first_and_return_ranking_highest_first():
    data = facts(eval_trace())
    mdd = ranking(data, "maximum drawdown")
    assert [o["name"] for o in mdd["order"]] == ["Consumer Staples", "Financials", "Utilities"]
    assert mdd["sentence"].startswith("Consumer Staples has the smallest maximum drawdown") and \
        mdd["sentence"].endswith("Utilities the deepest (-24.0%).")
    ret = ranking(data, "2022 return")
    assert [o["name"] for o in ret["order"]] == ["Consumer Staples", "Financials"]
    assert "Financials the lowest (-1.4%)" in ret["sentence"]


def test_values_that_print_the_same_are_tied():
    t = trace_with(industry("A", 0.15749, -0.1), industry("B", 0.15651, -0.2), industry("C", 0.17, -0.3))
    r = ranking(facts(t, {}), "annualized volatility")
    assert [o["rank"] for o in r["order"]] == [1, 1, 3]
    assert r["sentence"].startswith("A and B are tied for the lowest annualized volatility")
    t = trace_with(industry("A", 0.15749, -0.1), industry("B", 0.15651, -0.2))
    assert "have the same annualized volatility (15.7%)" in ranking(facts(t, {}), "annualized volatility")["sentence"]


def test_pairs_compare_requested_target_with_recommended_sector():
    pairs = {p["metric"]: p for p in facts(eval_trace())["pairs"]}
    assert pairs["annualized volatility"]["sentence"] == \
        "NVDA has a higher annualized volatility (51.1%) than Consumer Staples (17.0%)."
    assert pairs["maximum drawdown"]["sentence"] == \
        "NVDA has a deeper maximum drawdown (-63.5%) than Consumer Staples (-16.3%)."
    assert pairs["annualized volatility"]["steps"] == [1, 4]


def test_latest_successful_step_wins_and_errors_are_ignored():
    t = eval_trace()
    t.add(*industry("Utilities", 0.30, -0.5))  # re-run: the later result counts
    t.add("worker:risk_analyst", "analyze_sector", {"sector": "Energy"}, {"status": "error", "error": "boom"})
    order = ranking(facts(t), "annualized volatility")["order"]
    assert [o["name"] for o in order] == ["Financials", "Consumer Staples", "Utilities"]


def test_building_block_members_are_ranked_as_assets_not_as_a_group():
    t = trace_with(("worker:risk_analyst", "analyze_sector", {"sector": "Bonds"}, ok({
        "sector": "Bonds", "kind": "building_block", "member_metrics": {
            "TLT": {"annualized_vol": 0.161, "max_drawdown": -0.397, "total_return": -0.26},
            "ZST.TO": {"annualized_vol": 0.0056, "max_drawdown": -0.0043, "total_return": 0.18}}})))
    data = facts(t, {"recommended_sectors": ["Bonds"]})
    assert not [r for r in data["rankings"] if r["among"] == "sector groups"]
    assert ranking(data, "annualized volatility", "assets")["sentence"].startswith(
        "ZST.TO has the lowest annualized volatility among the assets analyzed (0.6%), TLT the highest (16.1%)")


def test_every_fact_sentence_passes_the_answer_check():
    t = eval_trace()
    out = comparisons.build(t, PLAN, as_of=AS_OF)
    step = t.add("worker:comparisons", "compare_metrics", {}, out)
    data = out["data"]
    text = "\n".join(f"- {f['sentence']} [fact: step {step}]" for f in data["rankings"] + data["pairs"])
    assert len(data["rankings"]) >= 4 and len(data["pairs"]) >= 3
    assert reviewer.check_answer(text, t) == {"verdict": "pass", "reasons": []}


def test_build_never_raises():
    class Broken:
        steps = None
        meta = {}
    assert comparisons.build(Broken(), PLAN)["status"] == "error"


# ---------- presenter: gets the facts, prompt forbids its own comparisons / outside concepts ----------

def test_presenter_input_includes_the_comparison_step():
    t = eval_trace()
    t.add("worker:comparisons", "compare_metrics", {}, comparisons.build(t, PLAN, as_of=AS_OF))
    assert "compare_metrics" in [s["action"] for s in presenter.relevant_steps(t, PLAN)]
    assert "NVDA has a higher annualized volatility (51.1%) than Consumer Staples (17.0%)." in \
        presenter.build_input(PERSONAS["robert"], "q", [], t, PLAN, [], None)


def test_presenter_prompt_rules():
    for lang in ("en", "fr"):
        p = presenter.system_prompt(PERSONAS["robert"], lang)
        assert "Never compare or rank numbers yourself" in p and "compare_metrics" in p
        assert "Copy each status EXACTLY" in p and "a pass is never \"info\"" in p
        assert "No concepts or claims that are not in the trace" in p
        # the old prompt listed "survivorship bias" as a limitation to write; the trace has no such warning
        limitations = p.split("7. **What could go wrong")[1].split("PLAIN LANGUAGE")[0]
        assert "survivorship" not in limitations.lower() and "Only" in limitations
