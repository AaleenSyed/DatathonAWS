"""Questionnaire -> custom profile (profile_builder.py), its API, and a full demo-mode run with it."""
import copy

import pytest
from fastapi.testclient import TestClient

import profile_builder as pb
import reviewer
from contract import assert_valid
from personas import PERSONAS
from server import agent
from server.app import create_app
from server.config import Settings
from workers import data_retriever as dr

needs_data = pytest.mark.skipif(not (dr.DATA_DIR / "macro_extra.csv").exists(),
                                reason="needs starter data + data/macro_extra.csv")
A, B = {"Authorization": "Bearer alice"}, {"Authorization": "Bearer bob"}
ROBERT_LIKE = dict(goal="income", horizon="3to5", drop25="sell_some", liquidity="some", crypto="none",
                   esg="not_important", industries=[])
AMIRA_LIKE = dict(goal="growth", horizon="10plus", drop25="buy_more", liquidity="none", crypto="significant",
                  esg="prefer", industries=["Information Technology"])


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("TRACE_S3", "0")
    yield
    pb.forget()  # registered profiles must not leak into other tests (they live in personas.PERSONAS)


def answers(scores=(0, 0, 0, 0), **extra):
    """Answers whose questions 1-4 have the given scores (0-3 each)."""
    base = {q: opts[s] for (q, opts), s in zip(pb.SCORED.items(), scores)}
    return {"crypto": "none", "esg": "not_important", "industries": [], **base, **extra}


# ---------- risk level ----------

@pytest.mark.parametrize("scores,level", [
    ((0, 0, 0, 0), "low"), ((1, 1, 1, 0), "low"), ((1, 1, 1, 1), "low-moderate"), ((2, 2, 2, 0), "low-moderate"),
    ((2, 2, 2, 1), "moderate"), ((3, 3, 3, 0), "moderate"), ((3, 3, 3, 1), "high"), ((3, 3, 3, 3), "high"),
])
def test_risk_level_boundaries(scores, level):
    assert pb.risk_level(pb.validate(answers(scores))) == level and pb.score(answers(scores)) == sum(scores)


# ---------- limits per level ----------

def test_low_level_table():
    p = pb.build(answers((1, 1, 1, 0)))  # 3 = low, horizon 3-5
    assert p["risk_tolerance"] == "low"
    assert p["limits"] == {"crypto_max": 0.0, "single_stock_max": 0.05, "vol_max": 0.08, "bonds_cash_min": 0.60}


def test_low_moderate_is_roberts_limits():
    p = pb.build(ROBERT_LIKE)
    assert p["risk_tolerance"] == "low-moderate" and p["limits"] == PERSONAS["robert"]["limits"]


def test_moderate_is_mateos_limits():
    p = pb.build(answers((2, 2, 2, 1)))
    assert p["risk_tolerance"] == "moderate" and p["limits"] == PERSONAS["mateo"]["limits"]


def test_high_is_amiras_limits():
    p = pb.build(AMIRA_LIKE)
    assert p["risk_tolerance"] == "high" and p["limits"] == PERSONAS["amira"]["limits"]


def test_tables_are_copies_not_the_personas():
    p = pb.build(AMIRA_LIKE)
    p["limits"]["sector_max"]["Information Technology"] = 0.9
    assert PERSONAS["amira"]["limits"]["sector_max"]["Information Technology"] == 0.5


# ---------- adjustments ----------

@pytest.mark.parametrize("scores,crypto,expected", [
    ((3, 3, 3, 3), "significant", 0.15), ((3, 3, 3, 3), "small", 0.05), ((3, 3, 3, 3), "none", 0.0),
    ((2, 2, 2, 1), "significant", 0.05), ((2, 2, 2, 1), "small", 0.05),   # moderate caps crypto at 5%
    ((1, 1, 1, 1), "significant", 0.0), ((0, 0, 0, 0), "significant", 0.0),  # low and low-moderate: none
])
def test_crypto_follows_q5_capped_by_level(scores, crypto, expected):
    p = pb.build(answers(scores, crypto=crypto))
    assert p["limits"]["crypto_max"] == expected
    assert 5 in p["limit_reasons"]["crypto_max"]["questions"]


def test_strict_esg_adds_energy_review():
    p = pb.build(answers((2, 2, 2, 1), esg="strict"))
    assert p["esg_review_tickers"] == ["ENB.TO", "CNQ.TO", "XOM"]
    assert p["limit_reasons"]["esg_review"]["questions"] == [6]
    for esg in ("prefer", "not_important"):
        assert pb.build(answers((2, 2, 2, 1), esg=esg))["esg_review_tickers"] == []


@pytest.mark.parametrize("scores", [(3, 0, 3, 3), (2, 0, 3, 2), (1, 0, 1, 1), (0, 0, 0, 0)])
def test_short_horizon_needs_60_percent_bonds_cash(scores):
    p = pb.build(answers(scores))  # horizon "lt3" (score 0)
    assert p["horizon_years"] == "<3" and p["limits"]["bonds_cash_min"] == 0.60
    assert "bonds_min" not in p["limits"]  # replaced by the stricter bonds/cash minimum
    assert p["limit_reasons"]["bonds_cash_min"]["questions"] == [2]


def test_industries_become_preferences_not_limits():
    p = pb.build(answers((2, 2, 2, 1), industries=["Utilities", "Health Care", "Utilities"]))
    assert "interested in Utilities" in p["preferences"] and "interested in Health Care" in p["preferences"]
    assert sum("Utilities" in x for x in p["preferences"]) == 1
    assert p["limits"] == PERSONAS["mateo"]["limits"]


# ---------- schema and reasons ----------

def test_same_schema_as_personas_plus_reasons():
    p = pb.build(ROBERT_LIKE)
    assert set(PERSONAS["robert"]) <= set(p) and set(p) - set(PERSONAS["robert"]) == {"limit_reasons", "source"}
    assert p["age"] is None and p["occupation"] is None  # no personal data


@pytest.mark.parametrize("a", [ROBERT_LIKE, AMIRA_LIKE, answers((0, 0, 0, 0), esg="strict", crypto="small"),
                               answers((2, 2, 2, 1), crypto="significant")])
@pytest.mark.parametrize("lang", ["en", "fr"])
def test_one_reason_per_limit(a, lang):
    p = pb.build(a, lang)
    expected = set(p["limits"]) | ({"esg_review"} if p["esg_review_tickers"] else set())
    assert set(p["limit_reasons"]) == expected
    for r in p["limit_reasons"].values():
        assert r["text"].strip() and r["questions"] and all(1 <= q <= 7 for q in r["questions"])
        assert "_" not in r["text"]  # plain language, no rule codes


def test_french_reasons():
    p = pb.build(answers((2, 2, 2, 1), crypto="small"), "fr")
    assert p["name"] == "Investisseur personnalisé" and "5\u00a0%" in p["limit_reasons"]["crypto_max"]["text"]


@pytest.mark.parametrize("bad", [
    {}, {**ROBERT_LIKE, "goal": "rich"}, {**ROBERT_LIKE, "crypto": "lots"}, {**ROBERT_LIKE, "industries": ["Gold"]},
    {**ROBERT_LIKE, "industries": "Utilities"}, {**ROBERT_LIKE, "name": "Jane"}, {**ROBERT_LIKE, "age": 40},
])
def test_invalid_answers(bad):
    with pytest.raises(pb.ProfileError):
        pb.build(bad)


# ---------- registry ----------

def test_register_and_owner():
    key = pb.register(ROBERT_LIKE, "alice")
    assert pb.is_custom(key) and key in PERSONAS and PERSONAS[key]["limits"] == PERSONAS["robert"]["limits"]
    assert pb.get(key, owner="alice")["key"] == key and pb.get(key, owner="bob") is None
    pb.forget(key)
    assert key not in PERSONAS and pb.get(key) is None


# ---------- API ----------

@pytest.fixture
def client(tmp_path):
    def runner(persona, question, history, lang, on_step, session_id):
        return agent.run_turn(persona, question, history, lang, on_step, mode="demo", session_id=session_id,
                              runs_dir=tmp_path)
    return TestClient(create_app(Settings(agent_mode="demo"), runner=runner))


def test_api_create_get_and_ownership(client):
    r = client.post("/profiles", json={"answers": AMIRA_LIKE, "language": "fr"}, headers=A)
    assert r.status_code == 201, r.text
    prof = r.json()
    assert_valid(prof, "Persona")
    assert prof["id"].startswith("custom-") and prof["riskTolerance"] == "high" and prof["age"] is None
    assert prof["limits"] == PERSONAS["amira"]["limits"] and "Cryptomonnaies" in prof["limitReasons"]["crypto_max"]["text"]
    assert client.get(f"/profiles/{prof['id']}", headers=A).json() == prof
    assert client.get(f"/profiles/{prof['id']}", headers=B).status_code == 404  # another user's profile
    # only the owner can chat with it
    assert client.post("/conversations", json={"personaId": prof["id"]}, headers=B).status_code == 400
    conv = client.post("/conversations", json={"personaId": prof["id"]}, headers=A)
    assert conv.status_code == 201 and conv.json()["personaId"] == prof["id"]
    assert_valid(conv.json(), "Conversation")
    # the built-in list is unchanged
    assert {p["id"] for p in client.get("/personas", headers=A).json()["items"]} == set(pb.BUILTIN)


@pytest.mark.parametrize("body", [{"answers": {**ROBERT_LIKE, "horizon": "forever"}}, {"answers": ROBERT_LIKE, "x": 1},
                                  {"answers": {**ROBERT_LIKE, "income": 90000}}])
def test_api_rejects_bad_answers(client, body):
    r = client.post("/profiles", json=body, headers=A)
    assert r.status_code == 400 and r.json()["code"] == "invalid_request"


def test_api_unknown_persona_is_rejected(client):
    assert client.post("/conversations", json={"personaId": "custom-zzzzzzzz"}, headers=A).status_code == 400
    assert client.post("/conversations", json={"personaId": "bob"}, headers=A).status_code == 400


# ---------- the pipeline, unchanged, with a custom profile ----------

@needs_data
@pytest.mark.parametrize("a,question", [
    (answers((0, 0, 0, 0), esg="strict"), "Best industry for the quickest gains"),
    (AMIRA_LIKE, "I only want AI and crypto, which industry should I focus on?"),
    (ROBERT_LIKE, "I want to put a big part of my savings in NVDA, good idea?"),
])
def test_demo_pipeline_with_custom_profile(tmp_path, a, question):
    key = pb.register(a, "alice")
    limits = copy.deepcopy(PERSONAS[key]["limits"])
    r = agent.run_turn(key, question, [], "en", mode="demo", runs_dir=tmp_path)
    assert r["work_verdict"]["verdict"] == "pass", r["work_verdict"]
    assert r["answer_verdict"]["verdict"] == "pass", r["answer_verdict"]
    assert reviewer.check_answer(r["answer"], r["trace"])["verdict"] == "pass"
    suit = [s for s in r["trace"].steps if s["action"] == "check_suitability" and s["output"]["status"] == "ok"]
    assert suit and all(s["input"]["persona"] == key for s in suit)
    rules = {c["rule"] for s in suit for c in s["output"]["data"]["checks"]}
    assert set(limits) <= rules  # every custom limit is evaluated
    recs = r["plan"]["recommended_sectors"]
    assert recs and not any(s["output"]["data"]["overall"] == "conflict" for s in suit
                            if s["input"]["target"] in recs and s["input"].get("proposed_weight") is None)
    if PERSONAS[key]["esg_review_tickers"]:
        flagged = {t for s in suit for c in s["output"]["data"]["checks"]
                   if c["rule"] == "esg_review" and c["status"] == "flag" for t in c["value"]}
        assert flagged == {"ENB.TO", "CNQ.TO", "XOM"}
    assert "Custom investor" in r["answer"]  # the disclaimer names the profile


@needs_data
def test_custom_profile_over_the_websocket(client):
    prof = client.post("/profiles", json={"answers": ROBERT_LIKE}, headers=A).json()
    conv = client.post("/conversations", json={"personaId": prof["id"]}, headers=A).json()
    ticket = client.post("/ws-ticket", headers=A).json()["ticket"]
    with client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        ws.send_json({"type": "message.send", "conversationId": conv["id"], "text": "Which industry fits me?"})
        while True:
            e = ws.receive_json()
            assert_valid(e, "WsServerMessage")
            if e["type"] == "message.end":
                break
    msg = e["message"]
    assert msg["status"] == "complete" and msg["final"]["persona"] == {"id": prof["id"], "name": "Custom investor"}
    assert msg["final"]["personaLimits"] == PERSONAS["robert"]["limits"]
