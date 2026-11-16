"""Intent router: classifies each user message before the pipeline. It never writes the reply.

Intents: analysis (default, follow-ups included), smalltalk, about, off_topic. Cheapest first:
1. greeting / thanks / bye regex (EN + FR), full match on the normalized message -> smalltalk
2. reviewer.extract_targets(question) non-empty -> analysis
3. "who are you / what can you do / comment ça marche ..." -> about
4. Claude Haiku 4.5 on Bedrock (ROUTER_MODEL): tiny Strands agent, no tools, structured output
5. any error, bad output or doubt -> analysis
Thread safety: runs outside server.agent.RUN_LOCK, so it must never touch agent_tools.CONTEXT.
The LLM step is off with llm=False, ROUTER_LLM=0 or AGENT_MODE=demo.
"""
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

import reviewer

load_dotenv(Path(__file__).resolve().parent / ".env")
PROMPTS = Path(__file__).resolve().parent / "prompts"
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
ROUTER_MAX_TOKENS = 200
ROUTER_LIMITS = {"turns": 2}  # 1 expected
INTENTS = ("analysis", "smalltalk", "about", "off_topic")
PREV_ANSWER_CHARS = 300
QUESTION_CHARS = 1000

# All patterns run on normalize(text): lower case, accents removed, punctuation -> one space.
_GREET = (r"hi|hello|hey|heya|hiya|yo|howdy|greetings|good (?:morning|afternoon|evening|day)"
          r"|bonjour|rebonjour|bonsoir|salut|allo|coucou|bon matin|bon apres midi")
_HOW = (r"how are you(?: doing)?(?: today)?|how s it going|how is it going|what s up"
        r"|ca va(?: bien)?|comment ca va|comment vas tu|comment allez vous")
_THANKS = (r"(?:(?:ok|okay|great|perfect|cool|nice|super|parfait|genial|d accord) )?"
           r"(?:thanks(?: a lot| so much| very much| again)?|thank you(?: very much| so much| again)?|thx|ty"
           r"|much appreciated|merci(?: beaucoup| bien| infiniment| encore| bcp)?|grand merci)")
_BYE = (r"bye(?: bye)?|goodbye|good bye|good night|see you(?: later| soon)?|see ya|take care"
        r"|have a (?:good|nice|great) (?:day|evening|night|one)"
        r"|au revoir|a bientot|a plus(?: tard)?|a la prochaine|bonne (?:journee|soiree|nuit)|ciao")
_TAIL = r"(?: (?:there|everyone|all|again|toi|vous|a tous|tout le monde|alphaforge(?: ai)?|amira|mateo|robert))?"
_PHRASE = rf"(?:{_GREET}|{_HOW}|{_THANKS}|{_BYE}){_TAIL}"
SMALLTALK = re.compile(rf"{_PHRASE}(?: {_PHRASE}){{0,3}}")  # use fullmatch
THANKS_BYE = re.compile(rf"\b(?:{_THANKS}|{_BYE})\b")
HELP = {"help", "help me", "aide", "aide moi", "aidez moi", "a l aide"}
ABOUT = re.compile("|".join([
    r"who are you", r"what are you",
    r"what (?:can|could|do) you do",
    r"what can i ask(?: you| here)?", r"what should i ask(?: you)?",
    r"how (?:do|does) (?:you|this|alphaforge)(?: ai)?(?: app| tool| site| chatbot| thing)? works?",
    r"how (?:do|can|should) i use (?:you|this|it|alphaforge)",
    r"what (?:is|s) (?:this(?: app| tool| site| chatbot| thing)?|alphaforge(?: ai)?)(?: for| about)?$",
    r"are you (?:a |an )?(?:bot|robot|ai|human|chatbot|llm|real person|real advisor|financial advisor|real)",
    r"where (?:do|does) (?:your|the|these|those) (?:data|numbers|figures|sources) come from",
    r"where do you get (?:your|the|these|those) (?:data|numbers|figures|sources)",
    r"what (?:data|sources) do you use",
    r"qui es tu", r"qui etes vous", r"(?:tu es|t es|vous etes) qui",
    r"c est quoi (?:alphaforge(?: ai)?|ce site|cette app(?:lication)?|cet outil|ce chatbot|ce robot)",
    r"qu est ce que (?:tu peux|tu sais|vous pouvez|vous savez) faire",
    r"que (?:peux tu|sais tu|pouvez vous|savez vous) faire",
    r"(?:tu peux|tu sais|vous pouvez|vous savez) faire quoi",
    r"comment (?:ca|cela|ce site|cet outil|cette app(?:lication)?|alphaforge) (?:marche|fonctionne)",
    r"comment (?:fonctionnes|marches) tu", r"comment (?:fonctionnez|marchez) vous",
    r"comment (?:t|vous) utiliser",
    r"(?:es tu|tu es|etes vous|vous etes) (?:un |une )?(?:robot|bot|ia|humaine?|vraie? personne|vrai conseiller|chatbot)",
    r"d ou viennent (?:tes|vos|les|ces) (?:donnees|chiffres|sources)",
    r"quelles (?:donnees|sources) (?:utilises tu|utilisez vous)",
    r"(?:que puis je|qu est ce que je peux) (?:te |vous )?demander",
]))
# with history these short phrases stay "about"; anything else may be a follow-up ("how does that work?")
ABOUT_STRICT = re.compile("|".join([
    r"who are you", r"what are you", r"what (?:can|could|do) you do",
    r"are you (?:a |an )?(?:bot|robot|ai|human|chatbot|llm|real person|real advisor|financial advisor|real)",
    r"qui es tu", r"qui etes vous", r"que (?:peux tu|pouvez vous) faire",
    r"(?:es tu|etes vous) (?:un |une )?(?:robot|bot|ia|humaine?|vraie? personne|vrai conseiller|chatbot)",
]))
KEYWORDS = re.compile(r"\b(?:" + "|".join("""invest investing investment industry industries sector sectors portfolio
stock stocks share shares etf bond bonds risk risky volatility return returns dividend savings retirement diversify
diversification growth crypto bitcoin market markets secteur secteurs industrie investir investissement placement
placements portefeuille action actions obligation obligations risque risquee rendement epargne retraite croissance
diversifier bourse fnb cryptomonnaie""".split()) + r"|(?<!ca )(?<!cela )marche)\b")


class RouteDecision(BaseModel):
    """Intent of the user's new message."""
    intent: Literal["analysis", "smalltalk", "about", "off_topic"] = Field(
        description="analysis = investing question or follow-up (default when unsure); smalltalk = greeting, "
                    "thanks, bye; about = question about the assistant; off_topic = unrelated to investing")
    reason: str = Field(description="at most 12 words: why this intent")


def normalize(s) -> str:
    s = unicodedata.normalize("NFKD", str(s).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _is_about(n: str, history=None) -> bool:
    if n in HELP:
        return True
    if history:
        return bool(ABOUT_STRICT.fullmatch(n))
    m = ABOUT.search(n)
    # a long message around the match is probably a real question: leave it to the LLM
    return bool(m) and len(n[:m.start()].split()) <= 3 and len(n[m.end():].split()) <= 2


def reply_key(intent: str, question: str) -> str:
    """texts.py key of the fixed reply for a non-analysis intent."""
    if intent == "smalltalk":
        return "chat_thanks" if THANKS_BYE.search(normalize(question)) else "chat_hello"
    return {"about": "chat_about", "off_topic": "chat_off_topic"}[intent]


def llm_enabled() -> bool:
    return os.getenv("ROUTER_LLM", "1") != "0" and os.getenv("AGENT_MODE", "bedrock").strip().lower() != "demo"


def build_prompt(question: str, history: list[dict]) -> str:
    prev = history[-1] if history else {}
    return (f"Previous question: {str(prev.get('question') or '(none)')[:QUESTION_CHARS]}\n"
            f"Previous answer (start): {str(prev.get('answer') or '(none)')[:PREV_ANSWER_CHARS]}\n"
            f"NEW MESSAGE: {question[:QUESTION_CHARS]}")


def llm_classify(question: str, history: list[dict]) -> dict:
    """One Bedrock call. Same method as pipeline.make_boss (Strands + structured_output_model), no tools,
    no hooks. Returns {"intent", "reason", "usage", "stop"}. May raise; route() catches."""
    from botocore.config import Config
    from strands import Agent
    from strands.models import BedrockModel

    # shortcut: model + agent built per call (never shared between threads); cache the model if latency matters
    model = BedrockModel(model_id=ROUTER_MODEL, region_name="us-east-1", max_tokens=ROUTER_MAX_TOKENS,
                         boto_client_config=Config(retries={"max_attempts": 5, "mode": "adaptive"}))
    agent = Agent(model=model, system_prompt=(PROMPTS / "router_system.txt").read_text(encoding="utf-8"),
                  callback_handler=None)
    r = agent(build_prompt(question, history), structured_output_model=RouteDecision, limits=ROUTER_LIMITS)
    u = getattr(getattr(r, "metrics", None), "accumulated_usage", None) or {}
    out = r.structured_output
    return {"intent": out.intent if out else None, "reason": out.reason if out else "no structured output",
            "usage": {k: int(u.get(k) or 0) for k in ("inputTokens", "outputTokens")}, "stop": str(r.stop_reason)}


def route(question: str, history: list[dict] | None = None, llm: bool = True, classify=None) -> dict:
    """{"intent", "method": "rule" | "llm" | "default", "reason", "model", "llm_ms", "usage", "stop"}. Never raises.
    classify: callable(question, history) -> {"intent", "reason", ...}; default llm_classify (injectable for tests)."""
    out = {"intent": "analysis", "method": "default", "reason": "", "model": None, "llm_ms": None, "usage": None,
           "stop": None}
    try:
        n = normalize(question)
        if n and SMALLTALK.fullmatch(n) and not (history and n in ("ca va", "ca va bien")):
            return {**out, "intent": "smalltalk", "method": "rule", "reason": "greeting / thanks / bye"}
        targets = reviewer.extract_targets(question)
        if targets:
            return {**out, "method": "rule", "reason": "names: " + ", ".join(targets[:5])}
        kw = KEYWORDS.search(n)
        if kw:
            return {**out, "method": "rule", "reason": f"investing keyword: {kw.group()}"}
        if _is_about(n, history):
            return {**out, "intent": "about", "method": "rule", "reason": "question about the assistant"}
        if not llm or (classify is None and not llm_enabled()):
            return {**out, "reason": "LLM step off"}
        out["model"] = ROUTER_MODEL
        t0 = time.perf_counter()
        try:
            r = (classify or llm_classify)(question, history or [])
        finally:
            out["llm_ms"] = (time.perf_counter() - t0) * 1000
        out.update(usage=r.get("usage"), stop=r.get("stop"))
        if r.get("intent") in INTENTS:
            return {**out, "intent": r["intent"], "method": "llm", "reason": str(r.get("reason") or "")}
        out["reason"] = f"bad router output: {r.get('intent')!r}"
    except Exception as e:
        out["reason"] = f"router error: {str(e)[:200]}"
    return out
