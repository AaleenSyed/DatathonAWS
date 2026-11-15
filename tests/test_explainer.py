"""ExplainerPayload built from a real run (demo agent = real workers), French answers, and the pipeline's new
history / language / live-step options."""
import pytest

import pipeline
import presenter
import reviewer
from contract import assert_valid
from personas import PERSONAS
from server import agent, explainer
from workers import data_retriever as dr

pytestmark = pytest.mark.skipif(not (dr.DATA_DIR / "macro_extra.csv").exists(),
                                reason="needs starter data + data/macro_extra.csv")
NVDA_Q = "I want to put a big part of my savings in NVDA, good idea?"


@pytest.fixture(autouse=True)
def no_s3(monkeypatch):
    monkeypatch.setenv("TRACE_S3", "0")


@pytest.fixture(scope="module")
def robert(tmp_path_factory):
    import os
    os.environ["TRACE_S3"] = "0"
    r = agent.run_turn("robert", NVDA_Q, [], "en", mode="demo", runs_dir=tmp_path_factory.mktemp("runs"))
    return r, explainer.build(r, "robert", "en")


def step(r, action, target=None):
    return [s for s in r["trace"].steps if s["action"] == action and s["output"].get("status") == "ok"
            and (target is None or target in (s["input"] or {}).values())][-1]


def test_payload_matches_contract(robert):
    _, final = robert
    assert_valid(final, "ExplainerPayload")
    assert final["persona"] == {"id": "robert", "name": "Robert"} and final["language"] == "en"
    assert final["personaLimits"] == PERSONAS["robert"]["limits"]
    assert final["review"] == {"work": {"verdict": "pass", "reasons": []}, "answer": {"verdict": "pass", "reasons": []},
                               "workRetries": 0, "answerRetries": 0, "incomplete": False}


def test_numbers_are_copied_from_the_cited_steps(robert):
    r, final = robert
    nvda = final["requestedTargets"][0]
    a = step(r, "analyze_asset", "NVDA")
    assert nvda["annualizedVol"] == a["output"]["data"]["annualized_vol"] and a["step"] in nvda["traceSteps"]
    assert nvda["suitabilityOverall"] == "conflict" and nvda["period"] == a["output"]["period"]
    staples = next(s for s in final["recommendedSectors"] if s["name"] == "Consumer Staples")
    sec = step(r, "analyze_sector", "Consumer Staples")
    mom = step(r, "sector_momentum", "Consumer Staples")
    assert staples["kind"] == "industry" and staples["annualizedVol"] == sec["output"]["data"]["annualized_vol"]
    assert staples["momentum12m"] == mom["output"]["data"]["basket"]["momentum_12m"]
    assert {m["ticker"] for m in staples["members"]} == {"ATD.TO", "PG"}
    bonds = next(s for s in final["recommendedSectors"] if s["name"] == "Bonds")
    assert bonds["kind"] == "building_block" and bonds["annualizedVol"] is None  # no blended figure
    assert bonds["range"]["annualizedVol"]["maxTicker"] == "TLT"


def test_risk_table_rows(robert):
    r, final = robert
    rows = {(row["group"], row["name"]): row for row in final["riskTable"]}
    assert set(rows) == {("NVDA", "NVDA"), ("Consumer Staples", "Consumer Staples"),
                         ("Bonds", "XBB.TO"), ("Bonds", "ZST.TO"), ("Bonds", "AGG"), ("Bonds", "TLT")}
    stress = step(r, "stress_test_2022", "NVDA")["output"]["data"]["NVDA"]
    assert rows[("NVDA", "NVDA")]["stress2022MaxDrawdown"] == stress["max_drawdown"]
    assert rows[("Bonds", "TLT")]["stress2022MaxDrawdown"] is None  # no 2022 step for Bonds in this run
    assert rows[("Bonds", "ZST.TO")]["annualizedVol"] < 0.03 < rows[("NVDA", "NVDA")]["annualizedVol"]


def test_suitability_keeps_every_status(robert):
    _, final = robert
    nvda = next(s for s in final["suitability"] if s["target"] == "NVDA")
    assert nvda["proposedWeight"] == 0.5 and nvda["overall"] == "conflict"
    statuses = {c["rule"]: c["status"] for c in nvda["checks"]}
    assert statuses["single_stock_max"] == "conflict" and statuses["vol_max"] == "flag"
    assert set(statuses) == set(PERSONAS["robert"]["limits"])  # every persona limit is reported


def test_market_context_and_claims(robert):
    r, final = robert
    cycle = step(r, "cycle_phase")["output"]["data"]
    mc = final["marketContext"]
    assert mc["phase"] == cycle["phase"] and mc["sectorTilt"] == cycle["sector_tilt"]
    facts = [c for c in final["claims"] if c["kind"] == "fact"]
    assert facts and all(c["traceSteps"] and c["sources"] for c in facts)
    assert any(c["kind"] == "assumption" for c in final["claims"])
    assert all("[fact" not in c["text"] and "**" not in c["text"] for c in final["claims"])
    assert set(final["caveats"]) >= {"simulation_only", "survivorship_bias"}


def test_claim_parsing_kinds_and_ranges(robert):
    r, _ = robert
    answer = ("- NVDA vol is high [fact: step 3, 5]. Bonds steady [fact: step 2-4].\n"
              "Historically X did well [fact: step 3] [assumption]. If rates rise [scenario].")
    got = explainer.claims(answer, r["trace"])
    assert [(c["kind"], c["traceSteps"]) for c in got] == [("fact", [3, 5]), ("fact", [2, 3, 4]),
                                                          ("assumption", [3]), ("scenario", [])]
    assert got[0]["text"] == "NVDA vol is high."


def test_french_numbers_are_checked(robert):
    r, _ = robert
    a = step(r, "analyze_asset", "NVDA")
    vol = a["output"]["data"]["annualized_vol"] * 100
    good = f"La volatilité de NVDA est de {vol:.1f} % [fact: step {a['step']}].".replace(".", ",", 1)
    assert "," in good and reviewer.check_answer(good, r["trace"], lang="fr")["verdict"] == "pass"
    bad = f"La volatilité de NVDA est de 43,3 % [fact: step {a['step']}]."
    assert reviewer.check_answer(bad, r["trace"], lang="fr")["verdict"] == "fail"
    assert reviewer.normalize_numbers("51,1\u00a0% et 1\u00a0254 jours", "fr") == "51.1\u00a0% et 1254 jours"
    assert reviewer.normalize_numbers("51,1", "en") == "51,1"
    assert reviewer.SENTENCE.split("Un [fact: step 1]. À noter [fact: step 2].") == ["Un [fact: step 1].",
                                                                                   "À noter [fact: step 2]."]


def test_presenter_prompt_per_language():
    p = PERSONAS["robert"]
    en, fr = presenter.system_prompt(p, "en"), presenter.system_prompt(p, "fr")
    assert "{{" not in en and "{{" not in fr
    assert "(Robert). Not personalized financial advice._" in en and "English" in en
    assert "Ne constitue pas un conseil financier personnalisé" in fr and "Canadian French" in fr
    assert "[fact: step N]" in fr  # tags stay machine-readable
    assert presenter.system_prompt(p, "de") == en  # unknown language -> English


class Presenter:
    def __init__(self):
        self.history = None

    def __call__(self, persona, question, history, trace, plan, notes, feedback=None):
        self.history = list(history)  # the session appends this turn afterwards
        return "Une réponse sans chiffres."


def test_pipeline_history_language_and_live_steps(tmp_path):
    boss, _ = __import__("server.demo_agent", fromlist=["make"]).make("robert", NVDA_Q, "fr")
    seen, pres = [], Presenter()
    earlier = [{"question": "q1", "answer": "a1"}]
    s = pipeline.ChatSession("robert", boss=boss, presenter=pres, history=earlier, lang="fr",
                             on_step=seen.append, runs_dir=tmp_path)
    r = s.ask(NVDA_Q)
    assert pres.history == earlier and r["trace"].meta["turn"] == 2 and r["trace"].meta["language"] == "fr"
    assert [x["step"] for x in seen] == [x["step"] for x in r["trace"].steps]
    assert r["answer"].endswith("Ne constitue pas un conseil financier personnalisé._")


def test_history_messages_alternate_and_keep_last_turns():
    turns = [{"question": f"q{i}", "answer": f"a{i}"} for i in range(5)] + [{"question": "q5", "answer": ""}]
    msgs = pipeline.history_messages(turns)
    assert [m["role"] for m in msgs] == ["user", "assistant"] * 2  # last 3 turns, the unanswered one dropped
    assert msgs[0]["content"][0]["text"] == "q3"


def test_listener_errors_do_not_break_the_trace():
    from run_trace import RunTrace

    def boom(step):
        raise RuntimeError("ui gone")
    t = RunTrace("Robert", "q", "2026-11-12", listener=boom)
    assert t.add("user", "question") == 1 and len(t.steps) == 1
