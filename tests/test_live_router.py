"""Live intent-router checks against Bedrock. Run: RUN_LIVE=1 python -m pytest -q -s tests/test_live_router.py"""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 (calls Bedrock)")

NVDA_HISTORY = [{"question": "I want to put a big part of my savings in NVDA, good idea?", "answer": "NVDA is a single stock ..."}]


@pytest.mark.parametrize("q,history,intent", [
    ("What do you think is the best option for someone like me?", [], "analysis"),
    ("And what about a smaller amount?", NVDA_HISTORY, "analysis"),
    ("you're awesome, have a great weekend", [], "smalltalk"),
    ("Dis-moi ce que tu fais comme travail ici", [], "about"),
    ("What's the weather in Montreal tomorrow?", [], "off_topic"),
    ("Peux-tu m'écrire un poème sur l'automne?", [], "off_topic"),
])
def test_live_route(q, history, intent):
    import router
    r = router.route(q, history)
    print(r)
    assert r["method"] == "llm"
    assert r["intent"] == intent
    assert r["llm_ms"] < 5000


def test_live_greeting_end_to_end():
    import pipeline
    r = pipeline.ChatSession("robert").ask("Bonjour")
    print(r["timing"])
    assert r["intent"] == "smalltalk"
    assert r["saved"]["local"]
    assert r["timing"]["total_ms"] < 2000
