"""Live end-to-end test of the web backend on Amazon Bedrock (Sonnet 5). Costs money, so only with RUN_LIVE=1:
    RUN_LIVE=1 python -m pytest -q -s tests/test_live_server.py
"""
import os

import pytest
from fastapi.testclient import TestClient

from contract import assert_valid
from server.app import create_app
from server.config import Settings

pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="live Bedrock test: set RUN_LIVE=1")
H = {"Authorization": "Bearer live-test"}


def until_end(ws):
    events = []
    while True:
        e = ws.receive_json()
        assert_valid(e, "WsServerMessage")
        events.append(e)
        if e["type"] == "message.end":
            return events


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(Settings(agent_mode="bedrock")))


def ask(client, conv, ws, text):
    ws.send_json({"type": "message.send", "conversationId": conv["id"], "text": text})
    msg = until_end(ws)[-1]["message"]
    print(f"\n===== {conv['personaId']} ({msg['language']}): {text}\n{msg['content']}\n"
          f"review={msg['final']['review']} s3={msg['final']['run']['s3Uri']}")
    return msg


def test_robert_nvda_in_french(client):
    conv = client.post("/conversations", json={"personaId": "robert", "language": "fr"}, headers=H).json()
    ticket = client.post("/ws-ticket", headers=H).json()["ticket"]
    with client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        msg = ask(client, conv, ws, "Je veux mettre une grande partie de mes économies dans NVDA, est-ce une bonne idée?")
    final = msg["final"]
    assert msg["status"] == "complete" and final["review"]["work"]["verdict"] == "pass"
    assert final["review"]["answer"]["verdict"] == "pass", final["review"]["answer"]
    assert "Ne constitue pas un conseil financier personnalisé" in msg["content"] and "[fact: step" in msg["content"]
    names = {s["name"] for s in final["recommendedSectors"]}
    assert names and not names & {"NVDA", "Information Technology"}
    assert any(s["target"] == "NVDA" and s["overall"] in ("conflict", "flag") for s in final["suitability"])
    assert final["run"]["s3Uri"] and final["run"]["s3Uri"].startswith("s3://")


def test_amira_follow_up_in_english_uses_history(client):
    conv = client.post("/conversations", json={"personaId": "amira"}, headers=H).json()
    ticket = client.post("/ws-ticket", headers=H).json()["ticket"]
    with client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        first = ask(client, conv, ws, "I only want AI and crypto, which industry should I focus on?")
        second = ask(client, conv, ws, "ok, and how much crypto can I hold at most?")
    for msg in (first, second):
        assert msg["status"] == "complete" and msg["final"]["review"]["answer"]["verdict"] == "pass"
    assert "15" in second["content"] and second["parentId"] != first["parentId"]
    crypto = [c for s in second["final"]["suitability"] for c in s["checks"] if c["rule"] == "crypto_max"]
    assert crypto and all(c["limit"] == 0.15 for c in crypto)
