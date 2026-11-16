"""Web backend tests: REST + WebSocket against the contract, using the demo agent (real workers, no LLM)."""
import threading
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from contract import assert_valid
from personas import PERSONAS
import router
from server import agent
from server.app import create_app
from server.auth import Authenticator, AuthError, TicketStore
from server.config import Settings
from texts import text_variant
from workers import data_retriever as dr

needs_data = pytest.mark.skipif(not (dr.DATA_DIR / "macro_extra.csv").exists(),
                                reason="needs starter data + data/macro_extra.csv")
NVDA_Q = "I want to put a big part of my savings in NVDA, good idea?"
A, B = {"Authorization": "Bearer alice"}, {"Authorization": "Bearer bob"}


@pytest.fixture(autouse=True)
def no_s3(monkeypatch):
    monkeypatch.setenv("TRACE_S3", "0")


class Runner:
    """Demo agent run that records its inputs; optionally blocks until released, or fails."""

    def __init__(self, runs_dir, block=False, fail=False):
        self.runs_dir, self.calls, self.fail = runs_dir, [], fail
        self.release = threading.Event()
        if not block:
            self.release.set()

    def __call__(self, persona, question, history, lang, on_step, session_id):
        self.calls.append({"persona": persona, "question": question, "history": history, "lang": lang})
        self.release.wait(10)
        if self.fail:
            raise RuntimeError("bedrock down")
        return agent.run_turn(persona, question, history, lang, on_step, mode="demo", session_id=session_id,
                              runs_dir=self.runs_dir)


def make_client(runner, settings=None, authenticator=None):
    return TestClient(create_app(settings or Settings(agent_mode="demo"), runner=runner, authenticator=authenticator))


@pytest.fixture
def runner(tmp_path):
    return Runner(tmp_path)


@pytest.fixture
def client(runner):
    return make_client(runner)


def new_conv(client, persona="robert", headers=A, **extra):
    r = client.post("/conversations", json={"personaId": persona, **extra}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def open_ws(client, headers=A):
    ticket = client.post("/ws-ticket", headers=headers).json()["ticket"]
    return client.websocket_connect(f"/ws?ticket={ticket}")


def until_end(ws, limit=500):
    """Events up to and including message.end; each one must match the contract."""
    events = []
    for _ in range(limit):
        e = ws.receive_json()
        assert_valid(e, "WsServerMessage")
        events.append(e)
        if e["type"] == "message.end":
            return events
    raise AssertionError("no message.end")


def turn(ws, conv, text, **extra):
    ws.send_json({"type": "message.send", "conversationId": conv["id"], "text": text, **extra})
    return until_end(ws)


# ---------- REST ----------

@needs_data
def test_health_needs_no_auth(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "agentMode": "demo", "authMode": "dev"}
    assert_valid(r.json(), "Health")


@needs_data
def test_dev_users_depend_on_token(client):
    anon, alice, bob = (client.get("/me", headers=h).json() for h in ({}, A, B))
    assert anon["id"] == "dev-user" and alice["id"] != bob["id"] and alice == client.get("/me", headers=A).json()
    for u in (anon, alice, bob):
        assert_valid(u, "User")


@needs_data
def test_personas_come_from_personas_py(client):
    body = client.get("/personas", headers=A).json()
    assert_valid(body, "PersonaList")
    got = {p["id"]: p for p in body["items"]}
    assert set(got) == set(PERSONAS)
    for key, p in PERSONAS.items():
        assert got[key]["limits"] == p["limits"] and got[key]["esgReviewTickers"] == p["esg_review_tickers"]
    assert got["robert"]["limits"]["stress_2022_max_drawdown"] == -0.15


@needs_data
def test_conversation_crud_and_pagination(client):
    first = new_conv(client)
    assert_valid(first, "Conversation")
    assert first["title"] == "New conversation" and first["language"] == "en" and first["activeLeafId"] is None
    fr = new_conv(client, "mateo", language="fr")
    assert fr["title"] == "Nouvelle conversation" and fr["language"] == "fr"
    third = new_conv(client, "amira", title="Tech")
    page = client.get("/conversations?limit=2", headers=A).json()
    assert_valid(page, "ConversationPage")
    assert [c["id"] for c in page["items"]] == [third["id"], fr["id"]] and page["nextCursor"] == "2"
    rest = client.get(f"/conversations?limit=2&cursor={page['nextCursor']}", headers=A).json()
    assert [c["id"] for c in rest["items"]] == [first["id"]] and rest["nextCursor"] is None
    patched = client.patch(f"/conversations/{first['id']}", json={"title": "Robert NVDA", "language": "fr"},
                           headers=A).json()
    assert patched["title"] == "Robert NVDA" and patched["language"] == "fr"
    assert client.delete(f"/conversations/{first['id']}", headers=A).status_code == 204
    assert client.get(f"/conversations/{first['id']}", headers=A).status_code == 404


@needs_data
def test_conversations_are_private(client):
    conv = new_conv(client, headers=A)
    for method, path, body in [("get", "", None), ("get", "/messages", None), ("patch", "", {"title": "x"}),
                               ("delete", "", None)]:
        r = client.request(method.upper(), f"/conversations/{conv['id']}{path}", json=body, headers=B)
        assert r.status_code == 404 and r.json()["code"] == "not_found"
        assert_valid(r.json(), "Error")
    assert client.get("/conversations", headers=B).json()["items"] == []


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/conversations", {"personaId": "bob"}),
    ("POST", "/conversations", {"personaId": "robert", "extra": 1}),
    ("POST", "/conversations", {"personaId": "robert", "language": "de"}),
    ("GET", "/conversations?limit=0", None),
    ("GET", "/conversations?cursor=abc", None),
])
@needs_data
def test_bad_requests_are_400(client, method, path, body):
    r = client.request(method, path, json=body, headers=A)
    assert r.status_code == 400 and r.json()["code"] == "invalid_request", r.text
    assert_valid(r.json(), "Error")


@needs_data
def test_patch_validation(client):
    conv = new_conv(client)
    for body in ({}, {"activeLeafId": "00000000-0000-0000-0000-000000000000"}, {"title": None}):
        r = client.patch(f"/conversations/{conv['id']}", json=body, headers=A)
        assert r.status_code == 400 and r.json()["code"] == "invalid_request", body


# ---------- auth ----------

class FakeJwks:
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, token):
        return self


@needs_data
def test_cognito_mode_verifies_id_tokens(runner):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = Settings(agent_mode="demo", cognito_pool_id="us-east-1_TEST", cognito_client_id="client123")
    auth = Authenticator(settings, jwks_client=FakeJwks(private.public_key()))
    client = make_client(runner, settings, auth)
    iss = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TEST"

    def token(**over):
        claims = {"sub": "u-1", "email": "amira@example.com", "aud": "client123", "iss": iss, "token_use": "id",
                  "exp": int(time.time()) + 600, **over}
        return {"Authorization": "Bearer " + jwt.encode(claims, private, algorithm="RS256")}

    ok = client.get("/me", headers=token())
    assert ok.status_code == 200 and ok.json() == {"id": "u-1", "email": "amira@example.com"}
    assert client.get("/health").json()["authMode"] == "cognito"
    for bad in ({}, token(aud="other"), token(token_use="access"), token(exp=int(time.time()) - 10),
                token(iss="https://evil.example")):
        r = client.get("/me", headers=bad)
        assert r.status_code == 401 and r.json()["code"] == "unauthorized"
        assert_valid(r.json(), "Error")


@needs_data
def test_tickets_are_single_use_and_expire():
    now = [100.0]
    store = TicketStore(ttl=30, clock=lambda: now[0])
    t = store.issue({"id": "u"})
    assert_valid(t, "WsTicket")
    assert store.redeem(t["ticket"]) == {"id": "u"}
    with pytest.raises(AuthError):
        store.redeem(t["ticket"])  # used
    t2 = store.issue({"id": "u"})
    now[0] += 31
    with pytest.raises(AuthError):
        store.redeem(t2["ticket"])  # expired


@needs_data
def test_ws_rejects_bad_ticket(client):
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/ws?ticket=nope") as ws:
            ws.receive_json()
    assert e.value.code == 4401


# ---------- WebSocket ----------

@needs_data
def test_ping_and_invalid_messages(client):
    conv = new_conv(client)
    with open_ws(client) as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        ws.send_text("not json")
        assert ws.receive_json()["code"] == "invalid_message"
        ws.send_json({"type": "message.send", "conversationId": conv["id"], "text": ""})
        assert ws.receive_json()["code"] == "invalid_message"
        ws.send_json({"type": "message.send", "conversationId": "00000000-0000-0000-0000-000000000000", "text": "hi"})
        assert ws.receive_json()["code"] == "not_found"
        ws.send_json({"type": "generation.cancel", "conversationId": conv["id"]})
        assert ws.receive_json()["code"] == "not_running"


@needs_data
def test_turn_streams_trace_and_ends_with_explanation(client, runner):
    conv = new_conv(client)
    with open_ws(client) as ws:
        events = turn(ws, conv, NVDA_Q, requestId="r1")
    start, end = events[0], events[-1]
    assert start["type"] == "message.start" and start["requestId"] == "r1"
    assert start["userMessage"]["content"] == NVDA_Q and start["message"]["status"] == "streaming"
    steps = [e["step"] for e in events if e["type"] == "trace.step"]
    assert [s["step"] for s in steps] == list(range(1, len(steps) + 1))  # live, in order, no gaps
    assert steps[0]["actor"] == "user" and steps[-1]["actor"] == "pipeline"
    stages = [e["stage"] for e in events if e["type"] == "generation.status"]
    assert stages[0] == "planning" and stages[-1] == "done" and "writing" in stages
    delta = next(e["delta"] for e in events if e["type"] == "message.delta")
    msg = end["message"]
    assert msg["status"] == "complete" and msg["content"] == delta and len(msg["trace"]) == len(steps)
    assert "Not personalized financial advice" in msg["content"]
    final = msg["final"]
    assert final["review"]["work"]["verdict"] == "pass" and final["review"]["answer"]["verdict"] == "pass"
    assert [s["name"] for s in final["requestedTargets"]] == ["NVDA"]
    assert final["requestedTargets"][0]["suitabilityOverall"] == "conflict"
    assert {s["name"] for s in final["recommendedSectors"]} == {"Consumer Staples", "Bonds"}
    # stored like it was streamed, and the conversation points at the reply
    stored = client.get(f"/conversations/{conv['id']}/messages", headers=A).json()
    assert_valid(stored, "MessageList")
    assert [m["role"] for m in stored["items"]] == ["user", "assistant"] and stored["items"][1] == msg
    conv_now = client.get(f"/conversations/{conv['id']}", headers=A).json()
    assert conv_now["activeLeafId"] == msg["id"] and conv_now["title"].startswith("I want to put")
    assert runner.calls[0]["persona"] == "robert" and runner.calls[0]["lang"] == "en"


@needs_data
def test_french_turn(client, runner):
    conv = new_conv(client, "mateo", language="fr")
    with open_ws(client) as ws:
        msg = turn(ws, conv, "Quelle industrie offre une croissance équilibrée pour moi?")[-1]["message"]
    assert runner.calls[0]["lang"] == "fr" and msg["language"] == "fr"
    assert "Recommandation" in msg["content"] and "Ne constitue pas un conseil financier personnalisé" in msg["content"]
    assert msg["final"]["language"] == "fr" and msg["final"]["review"]["answer"]["verdict"] == "pass"
    flagged = {t for s in msg["final"]["suitability"] for c in s["checks"]
               if c["rule"] == "esg_review" and c["status"] == "flag" for t in c["value"]}
    assert flagged == {"ENB.TO", "CNQ.TO", "XOM"}


@needs_data
def test_language_can_change_per_message(client, runner):
    conv = new_conv(client, "amira")
    with open_ws(client) as ws:
        msg = turn(ws, conv, "Où chercher de la croissance?", language="fr")[-1]["message"]
    assert runner.calls[0]["lang"] == "fr" and msg["language"] == "fr"


@needs_data
def test_follow_up_edit_and_regenerate_use_the_branch_history(client, runner):
    conv = new_conv(client)
    with open_ws(client) as ws:
        a1 = turn(ws, conv, NVDA_Q)[-1]["message"]
        e2 = turn(ws, conv, "And what about bonds?")
        u2, a2 = e2[0]["userMessage"], e2[-1]["message"]
        assert u2["parentId"] == a1["id"] and a2["parentId"] == u2["id"]
        assert runner.calls[1]["history"] == [{"question": NVDA_Q, "answer": a1["content"]}]

        ws.send_json({"type": "message.edit", "conversationId": conv["id"], "messageId": u2["id"],
                      "text": "And what about utilities?"})
        e3 = until_end(ws)
        u3, a3 = e3[0]["userMessage"], e3[-1]["message"]
        assert u3["parentId"] == a1["id"] and u3["id"] != u2["id"]  # sibling of the edited question
        assert runner.calls[2]["history"] == runner.calls[1]["history"]

        ws.send_json({"type": "message.regenerate", "conversationId": conv["id"], "messageId": a3["id"]})
        e4 = until_end(ws)
        assert "userMessage" not in e4[0]
        a4 = e4[-1]["message"]
        assert a4["parentId"] == u3["id"] and runner.calls[3]["question"] == "And what about utilities?"

        ws.send_json({"type": "message.send", "conversationId": conv["id"], "parentId": u3["id"], "text": "x"})
        assert ws.receive_json()["code"] == "invalid_message"  # a question must follow an answer
    items = client.get(f"/conversations/{conv['id']}/messages", headers=A).json()["items"]
    assert len(items) == 7  # u1 a1 | u2 a2 | u3 a3 a4
    assert client.get(f"/conversations/{conv['id']}", headers=A).json()["activeLeafId"] == a4["id"]
    # switch back to the first branch
    r = client.patch(f"/conversations/{conv['id']}", json={"activeLeafId": a2["id"]}, headers=A)
    assert r.status_code == 200 and r.json()["activeLeafId"] == a2["id"]


@needs_data
def test_busy_then_cancel(tmp_path):
    runner = Runner(tmp_path, block=True)
    client = make_client(runner)
    conv = new_conv(client)
    with open_ws(client) as ws:
        ws.send_json({"type": "message.send", "conversationId": conv["id"], "text": NVDA_Q})
        start = ws.receive_json()
        assert start["type"] == "message.start"
        assert ws.receive_json()["type"] == "generation.status"
        ws.send_json({"type": "message.send", "conversationId": conv["id"], "text": "again"})
        assert ws.receive_json()["code"] == "busy"
        ws.send_json({"type": "generation.cancel", "conversationId": conv["id"]})
        end = ws.receive_json()
        assert end["type"] == "message.end" and end["message"]["status"] == "cancelled"
        runner.release.set()  # the run finishes in the background; its result is discarded
        time.sleep(1.5)
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}  # no stray events from the cancelled run
        assert turn(ws, conv, "Is tech too risky for me?")[-1]["message"]["status"] == "complete"
    items = client.get(f"/conversations/{conv['id']}/messages", headers=A).json()["items"]
    assert [m["status"] for m in items if m["role"] == "assistant"] == ["cancelled", "complete"]


@needs_data
def test_agent_failure_is_reported(tmp_path):
    client = make_client(Runner(tmp_path, fail=True))
    conv = new_conv(client)
    with open_ws(client) as ws:
        events = turn(ws, conv, NVDA_Q)
    err = next(e for e in events if e["type"] == "error")
    assert err["code"] == "agent_error" and "bedrock down" in err["message"]
    assert events[-1]["message"]["status"] == "error"


@needs_data
def test_events_reach_every_socket_of_the_user(client):
    conv = new_conv(client)
    with open_ws(client) as ws1, open_ws(client) as ws2:
        events = turn(ws1, conv, NVDA_Q)
        mirrored = until_end(ws2)
    assert [e["type"] for e in mirrored] == [e["type"] for e in events]


# ---------- intent router: short replies ----------

def boom(*a, **k):
    raise AssertionError("LLM called")


@needs_data
def test_greeting_gets_short_reply_without_evidence(client, runner):
    conv = new_conv(client, "mateo", language="fr")
    with open_ws(client) as ws:
        events = turn(ws, conv, "Bonjour")
    msg = events[-1]["message"]
    assert msg["final"] is None and msg["status"] == "complete"
    assert msg["content"] == text_variant("fr", "chat_hello", 1, name="Mateo")
    assert [s["actor"] for s in msg["trace"]] == ["user", "router", "pipeline"]
    stages = [e["stage"] for e in events if e["type"] == "generation.status"]
    assert stages[-1] == "done" and "analyzing" not in stages
    assert next(e["delta"] for e in events if e["type"] == "message.delta") == msg["content"]
    stored = client.get(f"/conversations/{conv['id']}/messages", headers=A).json()
    assert_valid(stored, "MessageList")
    assert stored["items"][1] == msg and "_intent" not in stored["items"][1]


@needs_data
def test_short_replies_stay_out_of_history_and_rotate(client, runner):
    conv = new_conv(client)
    with open_ws(client) as ws:
        m1 = turn(ws, conv, "Hello")[-1]["message"]
        m2 = turn(ws, conv, NVDA_Q)[-1]["message"]
        turn(ws, conv, "And what about bonds?")
        m4 = turn(ws, conv, "hi")[-1]["message"]
    assert runner.calls[1]["history"] == [{"question": "Hello", "answer": m1["content"], "intent": "smalltalk"}]
    assert m2["final"] is not None
    assert runner.calls[2]["history"][-1] == {"question": NVDA_Q, "answer": m2["content"]}
    # 3 wordings: turn 4 wraps to turn 1's wording only if short-reply turns are counted (else turn 3)
    assert m4["content"] == m1["content"]


@needs_data
def test_greeting_does_not_wait_for_run_lock(tmp_path):
    out = {}
    agent.RUN_LOCK.acquire()
    try:
        t = threading.Thread(target=lambda: out.update(agent.run_turn("robert", "Bonjour", [], "fr", mode="demo",
                                                                      runs_dir=tmp_path)))
        t.start()
        t.join(10)
        assert not t.is_alive() and out["intent"] == "smalltalk"
    finally:
        agent.RUN_LOCK.release()


@needs_data
def test_demo_mode_never_calls_router_llm(tmp_path, monkeypatch):
    monkeypatch.delenv("ROUTER_LLM", raising=False)
    monkeypatch.setattr(router, "llm_classify", boom)
    r = agent.run_turn("robert", "hmm, what do you think?", [], "en", mode="demo", runs_dir=tmp_path)
    route = next(s for s in r["trace"].steps if s["action"] == "route")
    assert r["intent"] == "analysis" and route["output"]["method"] == "default"
    assert route["output"]["reason"] == "LLM step off"


@needs_data
def test_about_in_demo_mode(client, runner):
    conv = new_conv(client)
    with open_ws(client) as ws:
        msg = turn(ws, conv, "How does this work?")[-1]["message"]
    assert msg["final"] is None and msg["content"] == text_variant("en", "chat_about", 1, name="Robert")


def test_stage_for_router():
    assert agent.stage_for({"actor": "user", "action": "question"}) is None
    assert agent.stage_for({"actor": "router", "action": "route"}) == "planning"
