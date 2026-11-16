"""Intent router: classifies each user message before the pipeline and, for short replies, gets the chat text.

Intents: analysis (default, follow-ups included), smalltalk, about, explain, off_topic. Order, cheapest first:
0. "yes / oui" right after an explain reply -> analysis of the earlier question (rule)
1. greeting / thanks / bye regex (EN + FR) -> smalltalk (rule)
2. universe asset named, or investing keyword -> analysis (rule), unless the message is a definition question
3. "who are you / what can you do / comment ca marche ..." -> about (rule)
4. short message right after an analysis -> analysis (rule)
5. Claude Haiku 4.5 on Bedrock (ROUTER_MODEL): one call returns intent, confidence and the reply text. When a
   rule fixed the intent (smalltalk / about) the LLM only writes the reply; callers fall back to fixed texts.
6. any error, bad output or doubt (confidence not high) -> analysis
Replies must pass reply_problem() (no digit, %, universe asset, max length): the caller checks.
Thread safety: runs outside server.agent.RUN_LOCK, so it must never touch agent_tools.CONTEXT.
The LLM step is off with llm=False, ROUTER_LLM=0 or AGENT_MODE=demo.
"""
import functools
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

import reviewer
from workers import data_retriever as dr

load_dotenv(Path(__file__).resolve().parent / ".env")
PROMPTS = Path(__file__).resolve().parent / "prompts"
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
ROUTER_MAX_TOKENS = 500
ROUTER_LIMITS = {"turns": 2}  # 1 expected
INTENTS = ("analysis", "smalltalk", "about", "explain", "off_topic", "unclear")  # unclear: rule only (LLM off)
CHAT_TURNS = 4          # last turns (analysis and short replies) shown to the router
TURN_CHARS = 300        # per question and per answer
QUESTION_CHARS = 1000
REPLY_MAX_WORDS = 120
FOLLOWUP_MAX_WORDS = 4
LANG_NAME = {"en": "English", "fr": "Canadian French (fr-CA)"}

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
    r"what can you help (?:me )?with", r"how can you help(?: me)?", r"what do you help with",
    r"what (?:kind of )?(?:things|questions) can i ask",
    r"en quoi (?:peux tu|pouvez vous) m aider", r"comment (?:peux tu|pouvez vous) m aider",
    r"(?:tu peux|vous pouvez) m aider (?:avec|pour) quoi",
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
diversifier bourse fnb cryptomonnaie buy buying sell selling money afford acheter vendre argent""".split())
    + r"|good idea|worth it|bonne idee|vaut la peine|(?<!ca )(?<!cela )marche)\b")


DEFINE = re.compile(
    r"what does (.+) mean|what (?:is|s|are) (?:a |an |the )?(.+)|define (?:a |an |the )?(.+)"
    r"|explain (?:what )?(?:a |an |the )?(.+?)(?: is| are| means)?"
    r"|que (?:veut dire|signifie) (?:un |une |le |la |l |les )?(.+)"
    r"|c est quoi (?:un |une |le |la |l |les |des )?(.+)"
    r"|qu est ce qu (?:un|une) (.+)|qu est ce que (?:le |la |l |les )?(.+)"
    r"|expliquez?(?: moi)? (?:ce qu est |ce que sont )?(?:un |une |le |la |l |les )?(.+)")  # use fullmatch
PERSONAL = set("i me my mine we our us you your je j moi mon ma mes nous tu vous "
               "this that these those it ce cet cette ces ca cela".split())
_YES = (r"yes|yeah|yep|yup|sure|ok|okay|please|go ahead|do it|go for it|absolutely|of course"
        r"|oui|ouais|d accord|vas y|allez y|svp|s il vous plait|s il te plait|bien sur")
YES = re.compile(rf"(?:{_YES})(?: (?:{_YES})){{0,2}}")  # use fullmatch


class RouteDecision(BaseModel):
    """Intent of the user's new message and, when it is not analysis, the reply to show."""
    intent: Literal["analysis", "smalltalk", "about", "explain", "off_topic"] = Field(
        description="analysis = investing question or follow-up (default when unsure); smalltalk = greeting, "
                    "thanks, bye; about = question about the assistant; explain = what a general investing "
                    "term means; off_topic = unrelated to investing")
    confidence: Literal["high", "medium", "low"] = Field(description="how sure you are of the intent")
    reason: str = Field(description="at most 12 words, in English: why this intent")
    reply: str = Field(description="the reply shown to the user; empty string when intent is analysis")


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
    return {"about": "chat_about", "off_topic": "chat_off_topic", "unclear": "chat_unclear"}[intent]


def llm_enabled() -> bool:
    return os.getenv("ROUTER_LLM", "1") != "0" and os.getenv("AGENT_MODE", "bedrock").strip().lower() != "demo"


def _is_definition(n: str) -> bool:
    m = DEFINE.fullmatch(n)
    term = next(g for g in m.groups() if g).split() if m else []
    return 1 <= len(term) <= 3 and not set(term) & PERSONAL


def _tickers(text: str) -> list[str]:
    """Universe tickers named in text (ticker, company name, bitcoin / ethereum alias). [] when data is missing."""
    known = {r["ticker"] for r in dr.get_universe().get("data", [])}
    return [t for t in reviewer.extract_targets(text) if t in known]


def reply_problem(reply: str, as_of: str = "") -> str | None:
    """Why an LLM-written reply must not be shown (None = ok). Deterministic: every number must come from the workers."""
    if len(reply.split()) > REPLY_MAX_WORDS:
        return "too long"
    if re.search(r"[\d%]", reply.replace(as_of, "") if as_of else reply):
        return "contains a number"
    names = _tickers(reply)
    return ("names an asset: " + ", ".join(names[:3])) if names else None


def profile_text(persona: dict) -> str:
    keys = ("name", "age", "occupation", "risk_tolerance", "horizon_years", "goal")
    lines = [f"{k}: {persona[k]}" for k in keys if persona.get(k) is not None]
    prefs = [re.sub(r"\s*\([^)]*\)", "", str(p)) for p in persona.get("preferences") or []]  # drops "(e.g. NVDA, TSLA)"
    if prefs:
        lines.append("preferences: " + "; ".join(prefs))
    return "\n".join(lines) or "(unknown)"


def system_prompt(context: dict) -> str:
    return ((PROMPTS / "router_system.txt").read_text(encoding="utf-8")
            .replace("{{PROFILE}}", profile_text(context.get("persona") or {}))
            .replace("{{AS_OF}}", str(context.get("as_of") or "unknown"))
            .replace("{{LANGUAGE}}", LANG_NAME.get(context.get("lang"), LANG_NAME["en"])))


def build_prompt(question: str, context: dict) -> str:
    lines = []
    for t in (context.get("turns") or [])[-CHAT_TURNS:]:
        lines += [f"User: {str(t.get('question') or '')[:TURN_CHARS]}",
                  f"Assistant ({t.get('intent', 'analysis')}): {str(t.get('answer') or '')[:TURN_CHARS]}"]
    return ("CONVERSATION SO FAR (oldest first, context only):\n" + ("\n".join(lines) or "(none)")
            + f"\n\nNEW MESSAGE: {question[:QUESTION_CHARS]}")


@functools.lru_cache(maxsize=1)
def _model():
    """One shared BedrockModel (boto client is thread-safe); the Agent is built per call. Short timeouts:
    a slow Bedrock must not stall a greeting (route() falls back). Deliberately 2 attempts, not CLAUDE.md's 5."""
    from botocore.config import Config
    from strands.models import BedrockModel
    return BedrockModel(model_id=ROUTER_MODEL, region_name="us-east-1", max_tokens=ROUTER_MAX_TOKENS,
                        boto_client_config=Config(connect_timeout=2, read_timeout=3,
                                                  retries={"total_max_attempts": 2, "mode": "standard"}))


def llm_classify(question: str, context: dict) -> dict:
    """One Bedrock call (Strands + structured_output_model, no tools, no hooks). May raise; route() catches."""
    from strands import Agent
    agent = Agent(model=_model(), system_prompt=system_prompt(context), callback_handler=None)
    r = agent(build_prompt(question, context), structured_output_model=RouteDecision, limits=ROUTER_LIMITS)
    u = getattr(getattr(r, "metrics", None), "accumulated_usage", None) or {}
    out = r.structured_output
    return {"intent": out.intent if out else None, "confidence": out.confidence if out else None,
            "reason": out.reason if out else "no structured output", "reply": out.reply if out else "",
            "usage": {k: int(u.get(k) or 0) for k in ("inputTokens", "outputTokens")}, "stop": str(r.stop_reason)}


def route(question: str, history: list[dict] | None = None, llm: bool = True, classify=None,
          context: dict | None = None) -> dict:
    """{"intent", "method": "rule" | "llm" | "default", "reason", "model", "llm_ms", "usage", "stop",
    "confidence", "reply", "reply_note", "question"}. Never raises.
    history: earlier ANALYSIS turns (follow-up rules). context: {"persona", "lang", "as_of", "turns"} where turns =
    all earlier turns, short replies included (entries carry "intent"). classify: callable(question, context) ->
    {"intent", "confidence", "reason", "reply", ...}; default llm_classify (injectable for tests).
    reply: raw LLM text ("" = use the fixed text); the caller must run reply_problem() on it.
    question: set when the user accepted the offer after an explain reply (the earlier message to analyze)."""
    out = {"intent": "analysis", "method": "default", "reason": "", "model": None, "llm_ms": None, "usage": None,
           "stop": None, "confidence": None, "reply": "", "reply_note": None, "question": None}
    try:
        ctx = {"persona": {}, "lang": "en", "as_of": "", "turns": history or [], **(context or {})}
        last = ctx["turns"][-1] if ctx["turns"] else None
        n = normalize(question)
        use_llm = llm and (classify is not None or llm_enabled())
        if last and last.get("intent") == "explain" and YES.fullmatch(n):
            return {**out, "method": "rule", "reason": "accepted the analysis offer",
                    "question": str(last.get("question") or "") or None}
        if n and SMALLTALK.fullmatch(n) and not (history and n in ("ca va", "ca va bien")):
            out.update(intent="smalltalk", method="rule", reason="greeting / thanks / bye")
        else:
            targets = reviewer.extract_targets(question)
            known = {r["ticker"] for r in dr.get_universe().get("data", [])}
            define = use_llm and _is_definition(n) and not any(t in known for t in targets)
            if targets and not define:
                return {**out, "method": "rule", "reason": "names: " + ", ".join(targets[:5])}
            kw = KEYWORDS.search(n)
            if kw and not define:
                return {**out, "method": "rule", "reason": f"investing keyword: {kw.group()}"}
            if _is_about(n, history):
                out.update(intent="about", method="rule", reason="question about the assistant")
            elif (not define and last and last.get("intent", "analysis") == "analysis"
                  and 1 <= len(n.split()) <= FOLLOWUP_MAX_WORDS):
                return {**out, "method": "rule", "reason": "short follow-up to an analysis"}
        if not use_llm:
            if out["method"] == "rule":
                return {**out, "reply_note": "LLM step off"}
            if not (last and last.get("intent", "analysis") == "analysis"):  # no likely follow-up: don't run a report
                return {**out, "intent": "unclear", "method": "rule", "reason": "no investing signal (LLM off)",
                        "reply_note": "LLM step off"}
            return {**out, "reason": "LLM step off"}
        out["model"] = ROUTER_MODEL
        t0 = time.perf_counter()
        try:
            r = (classify or llm_classify)(question, ctx) or {}
        finally:
            out["llm_ms"] = (time.perf_counter() - t0) * 1000
        out.update(usage=r.get("usage"), stop=r.get("stop"), confidence=r.get("confidence"))
        if r.get("intent") not in INTENTS:
            raise ValueError(f"bad router output: {r.get('intent')!r}")
        reply = "" if r["intent"] == "analysis" else str(r.get("reply") or "").strip()
        if out["method"] == "rule":  # the rule's intent stands; the LLM only writes the reply
            return {**out, "reply": reply, "reply_note": None if reply else "no reply from the LLM"}
        reason = str(r.get("reason") or "")
        if r["intent"] != "analysis" and r.get("confidence") != "high":
            return {**out, "method": "llm",
                    "reason": f"{r['intent']} with {r.get('confidence')} confidence -> analysis: {reason}"}
        return {**out, "intent": r["intent"], "method": "llm", "reason": reason, "reply": reply,
                "reply_note": None if reply or r["intent"] == "analysis" else "no reply from the LLM"}
    except Exception as e:
        note = f"router error: {str(e)[:200]}"
        if out["method"] == "rule":
            out["reply_note"] = note   # greeting / about rule keeps its intent: fixed text
        else:
            out["reason"] = note       # anything else: analysis
    return out
