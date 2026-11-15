"""End-to-end demo questions on Amazon Bedrock (Sonnet 5). Costs money, so only with RUN_LIVE=1:
    RUN_LIVE=1 python -m pytest -q -s tests/test_live_demo.py
"""
import os

import pytest

import pipeline
import reviewer

pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="live Bedrock test: set RUN_LIVE=1")


def ask(persona, *questions):
    s = pipeline.ChatSession(persona)
    results = [s.ask(q) for q in questions]
    for q, r in zip(questions, results):
        print(f"\n===== {persona}: {q}\nwork={r['work_verdict']} answer={r['answer_verdict']} saved={r['saved']}\n")
        print(r["answer"])
    return results


def suit_steps(r, target):
    return [s["output"]["data"] for s in r["trace"].steps
            if s["action"] == "check_suitability" and s["output"]["status"] == "ok" and s["input"]["target"] == target]


def assert_clean(r):
    assert r["work_verdict"]["verdict"] == "pass", r["work_verdict"]
    assert r["answer_verdict"]["verdict"] == "pass", r["answer_verdict"]
    assert reviewer.check_answer(r["answer"], r["trace"])["verdict"] == "pass"
    assert "Not personalized financial advice" in r["answer"] and "[fact: step" in r["answer"]
    assert r["saved"]["local"] and r["saved"]["s3"]


def test_robert_nvda_is_challenged():
    (r,) = ask("robert", "I want to put a big part of my savings in NVDA, good idea?")
    assert_clean(r)
    assert any(d["overall"] in ("conflict", "flag") for d in suit_steps(r, "NVDA"))
    assert "NVDA" not in r["plan"]["recommended_sectors"] and "Information Technology" not in r["plan"]["recommended_sectors"]


def test_amira_ai_crypto_with_follow_up():
    r1, r2 = ask("amira", "I only want AI and crypto, which industry should I focus on?",
                 "ok, and how much crypto can I hold at most?")
    assert_clean(r1)
    assert_clean(r2)
    assert "15" in r2["answer"]  # crypto cap
    assert r2["trace"].meta["turn"] == 2


def test_mateo_balanced_with_esg_flag():
    (r,) = ask("mateo", "Which industry gives balanced growth for me?")
    assert_clean(r)
    flagged = {t for s in r["trace"].steps if s["action"] == "check_suitability" and s["output"]["status"] == "ok"
               for c in s["output"]["data"]["checks"] if c["rule"] == "esg_review" and c["status"] == "flag"
               for t in c["value"]}
    assert flagged & {"ENB.TO", "CNQ.TO", "XOM"}
    assert "ESG" in r["answer"]
