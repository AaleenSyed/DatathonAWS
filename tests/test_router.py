"""Intent router: rules, LLM path with a fake classifier (never Bedrock), fixed texts."""
import pytest

import router
from router import route
from texts import TEXT, text_variant
from workers import data_retriever as dr


def boom(*a, **k):
    raise AssertionError("LLM called")


def test_normalize():
    assert router.normalize("  Ça va ?! ") == "ca va"
    assert router.normalize("Qu’est-ce que c’est") == "qu est ce que c est"


@pytest.mark.parametrize("q", [
    "hi", "Hello!", "Hey there", "good morning", "thanks", "Thank you so much!", "ok thanks", "bye", "Hi Robert",
    "hello, how are you?", "Bonjour", "Bonjour!", "Salut", "Allô", "Bonsoir Mateo", "Merci beaucoup!",
    "Parfait, merci", "Ça va?", "Comment ça va ?", "À bientôt", "Au revoir", "Bonne journée!"])
def test_smalltalk_rule(q):
    r = route(q, classify=boom)
    assert (r["intent"], r["method"], r["llm_ms"]) == ("smalltalk", "rule", None)


@pytest.mark.parametrize("q", [
    "Who are you?", "What can you do?", "How does this work?", "what is AlphaForge AI?", "Are you a bot?",
    "Where does your data come from?", "help", "Qui es-tu?", "Qui êtes-vous ?", "Qu'est-ce que tu peux faire?",
    "Que pouvez-vous faire?", "Comment ça marche?", "Comment ça fonctionne ?", "C'est quoi AlphaForge?",
    "Es-tu un robot?", "D'où viennent tes données?", "Bonjour, qui es-tu?"])
def test_about_rule(q):
    r = route(q, classify=boom)
    assert (r["intent"], r["method"]) == ("about", "rule")


@pytest.mark.parametrize("q", ["Hello, is crypto ok for me?", "Bonjour, how does this work for bonds?",
                               "thanks, and what about tech?"])
def test_mixed_messages_are_analysis(q):
    r = route(q, classify=boom)
    assert (r["intent"], r["method"]) == ("analysis", "rule") and r["reason"].startswith("names:")


@pytest.mark.skipif(not (dr.DATA_DIR / "assets_universe.csv").exists(), reason="starter data not in data/")
def test_mixed_with_ticker():
    r = route("hi, can I buy NVDA?", classify=boom)
    assert (r["intent"], r["method"]) == ("analysis", "rule") and "NVDA" in r["reason"]


@pytest.mark.parametrize("q", ["ok", "yes", "oui"])
def test_not_rules(q):
    r = route(q, llm=False)
    assert (r["intent"], r["method"], r["reason"]) == ("analysis", "default", "LLM step off")


@pytest.mark.parametrize("intent", router.INTENTS)
def test_llm_each_intent(intent):
    seen = []

    def fake(q, h):
        seen.append((q, h))
        return {"intent": intent, "reason": "r", "usage": {"inputTokens": 40, "outputTokens": 6}, "stop": "end_turn"}
    hist = [{"question": "Q1", "answer": "A1"}]
    r = route("hmm, what do you think?", hist, classify=fake)
    assert (r["intent"], r["method"], r["model"]) == (intent, "llm", router.ROUTER_MODEL)
    assert r["usage"] == {"inputTokens": 40, "outputTokens": 6} and r["llm_ms"] >= 0
    assert seen == [("hmm, what do you think?", hist)]


def test_llm_errors_fall_back():
    def raises(q, h):
        raise RuntimeError("down")
    r = route("hmm, what do you think?", classify=raises)
    assert (r["intent"], r["method"]) == ("analysis", "default") and r["reason"].startswith("router error")
    r = route("hmm, what do you think?", classify=lambda q, h: {"intent": "explain"})
    assert (r["intent"], r["method"]) == ("analysis", "default") and "bad router output" in r["reason"]
    r = route("hmm, what do you think?", classify=lambda q, h: None)
    assert (r["intent"], r["method"]) == ("analysis", "default")


def test_llm_off_switches(monkeypatch):
    monkeypatch.setattr(router, "llm_classify", boom)
    q = "hmm, what do you think?"
    monkeypatch.setenv("ROUTER_LLM", "0")
    assert route(q)["method"] == "default"
    monkeypatch.delenv("ROUTER_LLM")
    monkeypatch.setenv("AGENT_MODE", "demo")
    assert route(q)["method"] == "default"
    assert route(q, llm=False, classify=boom)["method"] == "default"


def test_build_prompt():
    assert "Previous question: (none)" in router.build_prompt("hey?", [])
    p = router.build_prompt("the q", [{"question": "Q1", "answer": "A" * 500}])
    assert "Q1" in p and "A" * 300 in p and "A" * 301 not in p and p.endswith("NEW MESSAGE: the q")


def test_reply_key():
    assert router.reply_key("smalltalk", "Merci!") == "chat_thanks"
    assert router.reply_key("smalltalk", "bye") == "chat_thanks"
    assert router.reply_key("smalltalk", "Bonjour") == "chat_hello"
    assert router.reply_key("about", "x") == "chat_about"
    assert router.reply_key("off_topic", "x") == "chat_off_topic"


@pytest.mark.parametrize("lang", ["en", "fr"])
@pytest.mark.parametrize("key", ["chat_hello", "chat_thanks", "chat_about", "chat_off_topic"])
def test_fixed_texts(lang, key):
    options = TEXT[lang][key]
    assert isinstance(options, tuple) and len(options) in (2, 3)
    for i in range(1, len(options) + 1):
        t = text_variant(lang, key, i, name="Robert")
        assert "Robert" in t and "{" not in t
        if key == "chat_about":
            words = ("fictional", "sector", "source", "trace", "simulation", "advice") if lang == "en" else \
                    ("fictif", "secteur", "source", "trace", "simulation", "conseil")
            assert all(w in t.lower() for w in words)
    assert text_variant(lang, key, 1, name="R") != text_variant(lang, key, 2, name="R")
    assert text_variant(lang, key, 1, name="R") == text_variant(lang, key, len(options) + 1, name="R")


def test_prompt_file():
    t = (router.PROMPTS / "router_system.txt").read_text(encoding="utf-8")
    assert all(i in t for i in router.INTENTS)


HIST = [{"question": "Can I put money in NVDA?", "answer": "..."}]


@pytest.mark.parametrize("q", [
    "what can I do instead?", "what can I do now?", "what can i do with 10k", "what could you do for 50k",
    "how does that work?", "how does it work for Robert?", "comment ça marche?", "where do the numbers come from",
    "Ça va?"])
def test_followups_not_about_with_history(q):
    r = route(q, HIST, llm=False)
    assert (r["intent"], r["method"]) == ("analysis", "default")


@pytest.mark.parametrize("q", ["Who are you?", "What can you do?", "Comment ça marche?"])
def test_about_without_history(q):
    assert route(q, [], classify=boom)["intent"] == "about"


def test_strict_about_and_ca_va():
    assert route("Who are you?", HIST, classify=boom)["intent"] == "about"
    assert route("Ça va?", [], classify=boom)["intent"] == "smalltalk"


@pytest.mark.parametrize("q", ["Which industry gives balanced growth for me?", "Quel secteur pour la retraite?",
                               "what is this stock", "What can you do for my retirement savings plan?"])
def test_keyword_shortcut(q):
    r = route(q, classify=boom)
    assert (r["intent"], r["method"]) == ("analysis", "rule") and r["reason"].startswith("investing keyword:")
