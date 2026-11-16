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
    r = route(q, llm=False)
    assert (r["intent"], r["method"], r["llm_ms"]) == ("smalltalk", "rule", None)
    assert r["reply"] == "" and r["reply_note"] == "LLM step off"


@pytest.mark.parametrize("q", [
    "Who are you?", "What can you do?", "How does this work?", "what is AlphaForge AI?", "Are you a bot?",
    "Where does your data come from?", "help", "Qui es-tu?", "Qui êtes-vous ?", "Qu'est-ce que tu peux faire?",
    "Que pouvez-vous faire?", "Comment ça marche?", "Comment ça fonctionne ?", "C'est quoi AlphaForge?",
    "Es-tu un robot?", "D'où viennent tes données?", "Bonjour, qui es-tu?"])
def test_about_rule(q):
    r = route(q, llm=False)
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

    def fake(q, c):
        seen.append((q, c))
        return {"intent": intent, "confidence": "high", "reply": "Hello.", "reason": "r", "usage": {"inputTokens": 40, "outputTokens": 6}, "stop": "end_turn"}
    hist = [{"question": "Q1", "answer": "A1"}]
    r = route("hmm, what do you think?", hist, classify=fake)
    assert (r["intent"], r["method"], r["model"]) == (intent, "llm", router.ROUTER_MODEL)
    assert r["usage"] == {"inputTokens": 40, "outputTokens": 6} and r["llm_ms"] >= 0
    assert seen[0][0] == "hmm, what do you think?" and seen[0][1]["turns"] == hist
    assert r["reply"] == ("" if intent == "analysis" else "Hello.")


def test_llm_errors_fall_back():
    def raises(q, c):
        raise RuntimeError("down")
    r = route("hmm, what do you think?", classify=raises)
    assert (r["intent"], r["method"]) == ("analysis", "default") and r["reason"].startswith("router error")
    r = route("hmm, what do you think?", classify=lambda q, c: {"intent": "bogus"})
    assert (r["intent"], r["method"]) == ("analysis", "default") and "bad router output" in r["reason"]
    r = route("hmm, what do you think?", classify=lambda q, c: None)
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
    assert "(none)" in router.build_prompt("hey?", {})
    turns = [{"question": f"Q{i}", "answer": "A" * 500} for i in range(5)]
    turns[2]["intent"] = "smalltalk"
    p = router.build_prompt("the q", {"turns": turns})
    assert "Q0" not in p and all(f"Q{i}" in p for i in range(1, 5))
    assert "A" * 300 in p and "A" * 301 not in p
    assert "Assistant (smalltalk):" in p and "Assistant (analysis):" in p and p.endswith("NEW MESSAGE: the q")


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
    assert all(k in t for k in ("{{PROFILE}}", "{{AS_OF}}", "{{LANGUAGE}}"))


HIST = [{"question": "Can I put money in NVDA?", "answer": "..."}]


@pytest.mark.parametrize("q", [
    "what can I do instead?", "what can I do now?", "what can i do with 10k", "what could you do for 50k",
    "how does that work?", "how does it work for Robert?", "comment ça marche?", "where do the numbers come from",
    "Ça va?"])
def test_followups_not_about_with_history(q):
    r = route(q, HIST, llm=False)
    assert r["intent"] == "analysis" and r["method"] in ("rule", "default")


@pytest.mark.parametrize("q", ["Who are you?", "What can you do?", "Comment ça marche?"])
def test_about_without_history(q):
    assert route(q, [], llm=False)["intent"] == "about"


def test_strict_about_and_ca_va():
    assert route("Who are you?", HIST, llm=False)["intent"] == "about"
    assert route("Ça va?", [], llm=False)["intent"] == "smalltalk"


@pytest.mark.parametrize("q", ["Which industry gives balanced growth for me?", "Quel secteur pour la retraite?",
                               "what is this stock", "What can you do for my retirement savings plan?"])
def test_keyword_shortcut(q):
    r = route(q, classify=boom)
    assert (r["intent"], r["method"]) == ("analysis", "rule") and r["reason"].startswith("investing keyword:")


# ---- conversational replies ----
from personas import PERSONAS

needs_data = pytest.mark.skipif(not (dr.DATA_DIR / "assets_universe.csv").exists(), reason="starter data not in data/")


def llm_says(intent, confidence="high", reply="Sure thing."):
    return lambda q, c: {"intent": intent, "confidence": confidence, "reply": reply, "reason": "r"}


def test_greeting_gets_llm_reply():
    r = route("hi", classify=lambda q, c: {"intent": "smalltalk", "confidence": "low", "reply": " Hello! "})
    assert (r["intent"], r["method"], r["reply"]) == ("smalltalk", "rule", "Hello!") and r["llm_ms"] is not None


@pytest.mark.parametrize("q,intent", [("hi", "smalltalk"), ("Who are you?", "about")])
def test_rule_intent_survives_llm_failure(q, intent):
    def raises(q, c):
        raise RuntimeError("down")
    r = route(q, classify=raises)
    assert (r["intent"], r["method"], r["reply"]) == (intent, "rule", "") and r["reply_note"].startswith("router error")


def test_rule_intent_wins_over_llm_analysis():
    r = route("thanks", HIST, classify=llm_says("analysis"))
    assert r["intent"] == "smalltalk" and r["reply"] == "" and r["reply_note"] == "no reply from the LLM"


def test_analysis_reply_is_dropped():
    assert route("hmm, what do you think?", classify=llm_says("analysis", reply="x"))["reply"] == ""


@pytest.mark.parametrize("conf", ["medium", "low", None])
def test_low_confidence_goes_to_analysis(conf):
    r = route("hmm, what do you think?", classify=llm_says("off_topic", conf))
    assert (r["intent"], r["method"], r["reply"]) == ("analysis", "llm", "") and "confidence" in r["reason"]


@needs_data
@pytest.mark.parametrize("q", ["What does volatility mean?", "what is a bond?", "C'est quoi un FNB?",
                               "Qu'est-ce qu'une obligation?", "Explain diversification"])
def test_definition_goes_to_llm(q):
    r = route(q, classify=llm_says("explain"))
    assert (r["intent"], r["method"]) == ("explain", "llm")
    if q.startswith("What does"):
        off = route(q, llm=False)
        assert (off["intent"], off["method"]) == ("analysis", "rule")


@pytest.mark.parametrize("q", ["What does volatility mean for me?", "what is my risk",
                               "what is the best sector for growth"])
def test_not_definitions(q):
    r = route(q, classify=boom)
    assert (r["intent"], r["method"]) == ("analysis", "rule")


@needs_data
@pytest.mark.parametrize("q", ["what is NVDA?", "what is bitcoin"])
def test_not_definitions_with_asset(q):
    r = route(q, classify=boom)
    assert (r["intent"], r["method"]) == ("analysis", "rule")


def test_short_followup_rule():
    for q in ("why?", "tell me more", "ok"):
        r = route(q, HIST, classify=boom)
        assert (r["intent"], r["method"], r["reason"]) == ("analysis", "rule", "short follow-up to an analysis")
    calls = []

    def spy(q, c):
        calls.append(q)
        return {"intent": "analysis", "confidence": "high", "reply": "", "reason": "r"}
    route("why?", [], classify=spy)
    route("why?", [], classify=spy, context={"turns": [{"question": "hi", "answer": "Hello", "intent": "smalltalk"}]})
    assert calls == ["why?", "why?"]


@pytest.mark.parametrize("q", ["is it worth it", "can I afford that later on", "est-ce une bonne idée de faire ça",
                               "je veux acheter quelque chose"])
def test_new_keywords(q):
    r = route(q, classify=boom)
    assert (r["intent"], r["method"]) == ("analysis", "rule") and r["reason"].startswith("investing keyword:")


@pytest.mark.parametrize("m", ["yes", "Oui", "ok go ahead", "vas-y"])
def test_yes_after_explain(m):
    ctx = {"turns": [{"question": "What does volatility mean?", "answer": "...", "intent": "explain"}]}
    r = route(m, [], classify=boom, context=ctx)
    assert (r["intent"], r["method"], r["question"]) == ("analysis", "rule", "What does volatility mean?")
    assert route("yes", [], llm=False)["question"] is None


@needs_data
def test_reply_problem():
    for ok in ("Hello Robert! Happy to help.", "I can look at tech and bonds for you."):
        assert router.reply_problem(ok) is None
    assert router.reply_problem("My data ends on 2026-11-12.", "2026-11-12") is None
    for bad in ("about 7 a year", "ten %", "My data ends on 2026-11-12."):
        assert router.reply_problem(bad) == "contains a number"
    assert router.reply_problem("word " * 121) == "too long"
    assert router.reply_problem("NVDA is popular").startswith("names an asset")
    assert router.reply_problem("Apple is a company").startswith("names an asset")


def test_profile_text():
    t = router.profile_text(PERSONAS["robert"])
    assert "Robert" in t and "NVDA" not in t and "limits" not in t and "0.1" not in t
    assert str(PERSONAS["robert"]["risk_tolerance"]) in t
    c = router.profile_text({"name": "Custom investor", "age": None, "occupation": None, "risk_tolerance": "moderate",
                             "horizon_years": "5-10", "goal": "Balanced growth", "preferences": []})
    assert "None" not in c and "age" not in c


def test_system_prompt():
    p = router.system_prompt({"persona": PERSONAS["mateo"], "lang": "fr", "as_of": "2026-11-12"})
    assert "Mateo" in p and "Canadian French" in p and "2026-11-12" in p and "{{" not in p
