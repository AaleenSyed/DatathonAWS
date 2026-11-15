"""Build a fictional investor profile from a 7-question multiple-choice questionnaire. Deterministic, no LLM.

No personal data is collected: no name, age, income or amounts, only the answer codes below.

Risk level: questions 1-4 each score 0-3 (total 0-12):
    0-3 low · 4-6 low-moderate · 7-9 moderate · 10-12 high
Limits: a fixed table per level (team assumptions, like the personas' limits):
    low           crypto 0%, single stock <= 5%, volatility <= 8%, bonds/cash >= 60%
    low-moderate  Robert's limits      moderate  Mateo's limits      high  Amira's limits
Adjustments:
    Q5 crypto interest sets the crypto cap (none 0%, small 5%, significant 15%), capped by the level
        (low 0%, low-moderate 0%, moderate 5%, high 15%).
    Q6 "strictly avoid controversial companies" -> ESG review of the Energy names ENB.TO, CNQ.TO, XOM.
    Q2 horizon under 3 years -> bonds/cash at least 60% (replaces a lower bonds minimum).
    Q7 industries of interest -> preferences (used by the boss and the presenter, not as limits).

build() returns a persona dict with the SAME schema as personas.PERSONAS, plus "limit_reasons": one sentence per
limit with the questions that caused it. register() stores it in personas.PERSONAS under "custom-<8 chars>", so
the pipeline, workers, reviewer and explainer use it unchanged. Profiles live in memory (like conversations).
"""
import copy
import re
import secrets
import threading
from collections import OrderedDict

from personas import PERSONAS

CUSTOM_PREFIX = "custom-"
CUSTOM_KEY = re.compile(r"^custom-[a-z0-9]{8}$")
BUILTIN = ("amira", "mateo", "robert")
MAX_PROFILES = 500  # oldest profiles are dropped beyond this (memory bound)
SOURCE = "questionnaire answers (profile_builder.py); numeric limits are team assumptions"

# question -> option -> score (Q1-Q4) or meaning
SCORED = {
    "goal": ["preserve", "income", "balanced", "growth"],
    "horizon": ["lt3", "3to5", "5to10", "10plus"],
    "drop25": ["sell_all", "sell_some", "hold", "buy_more"],
    "liquidity": ["high", "some", "low", "none"],
}
CRYPTO = {"none": 0.0, "small": 0.05, "significant": 0.15}
ESG = ("not_important", "prefer", "strict")
QUESTION_NO = {"goal": 1, "horizon": 2, "drop25": 3, "liquidity": 4, "crypto": 5, "esg": 6, "industries": 7}
LEVELS = [(3, "low"), (6, "low-moderate"), (9, "moderate"), (12, "high")]
CRYPTO_CAP = {"low": 0.0, "low-moderate": 0.0, "moderate": 0.05, "high": 0.15}
ESG_TICKERS = ["ENB.TO", "CNQ.TO", "XOM"]
SHORT_HORIZON_BONDS_CASH = 0.60
HORIZON_YEARS = {"lt3": "<3", "3to5": "3-5", "5to10": "5-10", "10plus": "10+"}
GOAL = {"preserve": "Capital preservation", "income": "Income and stability", "balanced": "Balanced growth",
        "growth": "Long-term growth"}
NAME = {"en": "Custom investor", "fr": "Investisseur personnalisé"}

LEVEL_LIMITS = {
    "low": {"crypto_max": 0.0, "single_stock_max": 0.05, "vol_max": 0.08, "bonds_cash_min": 0.60},
    "low-moderate": PERSONAS["robert"]["limits"],
    "moderate": PERSONAS["mateo"]["limits"],
    "high": PERSONAS["amira"]["limits"],
}

_lock = threading.Lock()
_profiles: "OrderedDict[str, dict]" = OrderedDict()  # key -> {"owner", "answers", "lang"}


class ProfileError(ValueError):
    """Invalid questionnaire answers."""


def industries() -> list[str]:
    """Industry sector groups of the universe (the Q7 options)."""
    from workers import data_retriever as dr
    from workers import risk_analyst as ra
    groups: dict[str, list] = {}
    for r in dr.get_universe().get("data", []):
        groups.setdefault(r["sector"].split(" (")[0], []).append({"asset_class": r["asset_class"]})
    return [g for g, members in groups.items() if ra.group_kind(members) == "industry"]


def validate(answers: dict) -> dict:
    """Clean copy of the answers, or ProfileError. Only the 7 known questions are accepted."""
    if not isinstance(answers, dict):
        raise ProfileError("answers must be an object")
    extra = set(answers) - set(QUESTION_NO)
    if extra:
        raise ProfileError(f"unknown questions: {sorted(extra)}")
    out = {}
    for q, options in SCORED.items():
        if answers.get(q) not in options:
            raise ProfileError(f"{q} must be one of {options}")
        out[q] = answers[q]
    if answers.get("crypto") not in CRYPTO:
        raise ProfileError(f"crypto must be one of {list(CRYPTO)}")
    if answers.get("esg") not in ESG:
        raise ProfileError(f"esg must be one of {list(ESG)}")
    out["crypto"], out["esg"] = answers["crypto"], answers["esg"]
    chosen = answers.get("industries", [])
    if not isinstance(chosen, list) or not all(isinstance(x, str) for x in chosen):
        raise ProfileError("industries must be a list of sector group names")
    valid = industries()
    unknown = [x for x in chosen if x not in valid]
    if unknown:
        raise ProfileError(f"unknown industries {unknown}; choose from {valid}")
    out["industries"] = list(dict.fromkeys(chosen))
    return out


def score(answers: dict) -> int:
    return sum(SCORED[q].index(answers[q]) for q in SCORED)


def risk_level(answers: dict) -> str:
    total = score(answers)
    return next(level for top, level in LEVELS if total <= top)


# ---------- limit reasons (one sentence per limit, EN / FR) ----------

def _pct(x: float, lang: str) -> str:
    s = f"{x * 100:.1f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") + "\u00a0%" if lang == "fr" else s + "%"


LEVEL_NAME = {"en": {"low": "low", "low-moderate": "low-moderate", "moderate": "moderate", "high": "high"},
              "fr": {"low": "faible", "low-moderate": "faible à modéré", "moderate": "modéré", "high": "élevé"}}
T = {
    "en": {
        "level": "your {level} risk level",
        "crypto_none": "No crypto: you said you are not interested in crypto.",
        "crypto_capped": "No crypto, despite your interest in it: {because} allows none.",
        "crypto_cap": "Crypto at most {x}: your interest in crypto, capped by {because}.",
        "single_stock_max": "At most {x} in any single stock, to limit the damage one company can do, set by {because}.",
        "vol_max": "Annualized volatility at most {x}, set by {because}.",
        "bonds_cash_min": "At least {x} in bonds or cash, set by {because}.",
        "bonds_cash_short": "At least {x} in bonds or cash: you may need this money within 3 years.",
        "bonds_min": "At least {x} in bonds, set by {because}.",
        "stress": "A fall of at most {x} in the 2022 stress test, set by {because}.",
        "sector_max": "At most {x} in {sector}, so a high-risk profile stays diversified, set by {because}.",
        "min_asset_classes": "At least {n} asset classes, because high risk does not mean everything in one "
                             "place, set by {because}.",
        "esg_review": "{tickers} need an ESG review before use: you want to strictly avoid companies with "
                      "significant controversies.",
    },
    "fr": {
        "level": "votre niveau de risque {level}",
        "crypto_none": "Aucune cryptomonnaie : vous avez indiqué ne pas vous y intéresser.",
        "crypto_capped": "Aucune cryptomonnaie, malgré votre intérêt : {because} n’en permet aucune.",
        "crypto_cap": "Cryptomonnaies à {x} au maximum : votre intérêt, plafonné par {because}.",
        "single_stock_max": "Au plus {x} dans un seul titre, pour limiter l’effet d’une seule société, selon {because}.",
        "vol_max": "Volatilité annualisée d’au plus {x}, selon {because}.",
        "bonds_cash_min": "Au moins {x} en obligations ou en encaisse, selon {because}.",
        "bonds_cash_short": "Au moins {x} en obligations ou en encaisse : vous pourriez avoir besoin de cet argent "
                            "d’ici 3 ans.",
        "bonds_min": "Au moins {x} en obligations, selon {because}.",
        "stress": "Une baisse d’au plus {x} au test de stress 2022, selon {because}.",
        "sector_max": "Au plus {x} dans {sector}, pour qu’un profil à risque élevé reste diversifié, selon {because}.",
        "min_asset_classes": "Au moins {n} catégories d’actifs, car un risque élevé ne veut pas dire tout au même "
                             "endroit, selon {because}.",
        "esg_review": "{tickers} doivent faire l’objet d’un examen ESG : vous voulez éviter strictement les "
                      "sociétés faisant l’objet de controverses importantes.",
    },
}
LEVEL_QS = [1, 2, 3, 4]


def _reasons(limits: dict, level: str, answers: dict, esg_tickers: list, lang: str) -> dict:
    t = T[lang]
    because = t["level"].format(level=LEVEL_NAME[lang][level])
    out = {}
    for rule, value in limits.items():
        if rule == "crypto_max":
            if CRYPTO[answers["crypto"]] == 0:
                out[rule] = {"text": t["crypto_none"], "questions": [5]}
            elif value == 0:
                out[rule] = {"text": t["crypto_capped"].format(because=because), "questions": LEVEL_QS + [5]}
            else:
                out[rule] = {"text": t["crypto_cap"].format(x=_pct(value, lang), because=because),
                             "questions": LEVEL_QS + [5]}
        elif rule == "bonds_cash_min" and answers["horizon"] == "lt3":
            out[rule] = {"text": t["bonds_cash_short"].format(x=_pct(value, lang)), "questions": [2]}
        elif rule == "stress_2022_max_drawdown":
            out[rule] = {"text": t["stress"].format(x=_pct(abs(value), lang), because=because), "questions": LEVEL_QS}
        elif rule == "sector_max":
            sector, cap = next(iter(value.items()))
            out[rule] = {"text": t["sector_max"].format(x=_pct(cap, lang), sector=sector, because=because),
                         "questions": LEVEL_QS}
        elif rule == "min_asset_classes":
            out[rule] = {"text": t["min_asset_classes"].format(n=value, because=because), "questions": LEVEL_QS}
        else:
            out[rule] = {"text": t[rule].format(x=_pct(value, lang), because=because), "questions": LEVEL_QS}
    if esg_tickers:
        out["esg_review"] = {"text": t["esg_review"].format(tickers=", ".join(esg_tickers)), "questions": [6]}
    return out


# ---------- build / register ----------

def build(answers: dict, lang: str = "en") -> dict:
    """Persona dict (personas.PERSONAS schema + limit_reasons) from the questionnaire answers."""
    lang = lang if lang in T else "en"
    a = validate(answers)
    level = risk_level(a)
    limits = copy.deepcopy(LEVEL_LIMITS[level])
    limits["crypto_max"] = min(CRYPTO[a["crypto"]], CRYPTO_CAP[level])
    if a["horizon"] == "lt3":
        limits.pop("bonds_min", None)  # a bonds/cash minimum of 60% covers it
        limits["bonds_cash_min"] = max(limits.get("bonds_cash_min", 0.0), SHORT_HORIZON_BONDS_CASH)
    esg_tickers = list(ESG_TICKERS) if a["esg"] == "strict" else []
    preferences = [f"interested in {s}" for s in a["industries"]]
    preferences += {"strict": ["strong ESG preference",
                               "strictly avoid companies with significant environmental/social controversies"],
                    "prefer": ["prefers companies with good ESG practices"], "not_important": []}[a["esg"]]
    preferences += {"none": ["no interest in crypto"], "small": ["some interest in crypto"],
                    "significant": ["strong interest in crypto"]}[a["crypto"]]
    return {
        "name": NAME[lang],
        "age": None,          # not asked: no personal data
        "occupation": None,   # not asked
        "risk_tolerance": level,
        "horizon_years": HORIZON_YEARS[a["horizon"]],
        "goal": GOAL[a["goal"]],
        "preferences": preferences,
        "limits": limits,
        "esg_review_tickers": esg_tickers,
        "limit_reasons": _reasons(limits, level, a, esg_tickers, lang),
        "source": SOURCE,
    }


def is_custom(key: str) -> bool:
    return bool(CUSTOM_KEY.match(str(key or "")))


def register(answers: dict, owner: str, lang: str = "en") -> str:
    """Build the profile, store it in personas.PERSONAS under a new "custom-<8 chars>" key, return the key."""
    persona = build(answers, lang)
    with _lock:
        key = CUSTOM_PREFIX + secrets.token_hex(4)
        while key in PERSONAS:
            key = CUSTOM_PREFIX + secrets.token_hex(4)
        PERSONAS[key] = persona
        _profiles[key] = {"owner": owner, "answers": validate(answers), "lang": lang}
        while len(_profiles) > MAX_PROFILES:
            old, _ = _profiles.popitem(last=False)
            PERSONAS.pop(old, None)
    return key


def get(key: str, owner: str | None = None) -> dict | None:
    """{"key", "persona", "answers"} for a registered profile (only its owner's, when owner is given)."""
    with _lock:
        meta = _profiles.get(key)
        if meta is None or key not in PERSONAS or (owner is not None and meta["owner"] != owner):
            return None
        return {"key": key, "persona": PERSONAS[key], "answers": dict(meta["answers"])}


def forget(key: str | None = None):
    """Remove one profile (or all custom profiles). Used by tests."""
    with _lock:
        for k in [key] if key else list(_profiles):
            _profiles.pop(k, None)
            PERSONAS.pop(k, None)
