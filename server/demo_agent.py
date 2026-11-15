"""Demo agent (AGENT_MODE=demo): a scripted boss and presenter, no LLM, no Bedrock cost.

The boss calls the REAL worker tools with a fixed plan, so every number is real and passes the reviewer;
the presenter fills a template from the trace (English or French). Use it to develop the UI. The answer
says it is a demo; never present it as the agent's reasoning.
"""
import re

import agent_tools as at
import reviewer
from personas import PERSONAS
from workers import data_retriever as dr

RECOMMEND = {"robert": ["Consumer Staples", "Bonds"], "amira": ["Information Technology", "Bonds"],
             "mateo": ["Utilities", "Bonds"]}
BIG_SHARE = re.compile(r"\b(big|large|most|all|majority|bulk|grande?|gros|majorit\w*|tout|toute|"
                       r"l[’']essentiel|beaucoup)\b", re.I)
PERCENT = re.compile(r"(\d{1,3})\s*%")

T = {
    "en": {"demo": "Demo mode: scripted answer from the real worker numbers (no LLM).",
           "rec": "Recommendation", "why": "Why it fits", "check": "Profile check", "assets": "Example assets",
           "market": "Market context", "esg": "ESG review", "risks": "What could go wrong / limitations",
           "fit": "For {name}'s profile, the sector groups that fit best here are {recs}.",
           "conflict": "The request conflicts with {name}'s profile: {target} is a {status} on {rules}.",
           "vol": "{t}: annualized volatility {vol}, max drawdown {mdd}.",
           "range": "{t}: annualized volatility from {lo} ({lot}) to {hi} ({hit}) across its members.",
           "mom": "{t}: 12-month momentum {m}, {trend}.",
           "rule": "{rule}: {status}, {value} vs a limit of {limit}.",
           "members": "{t}: {members}.",
           "phase": "Historically, in a {phase} phase, sectors like {tilt} have tended to do relatively well; "
                    "this is a historical tendency, not a prediction.",
           "esg_flag": "{names} need an ESG review; evidence is not yet available in this prototype.",
           "limits": "Past returns do not predict future returns, and sector baskets are equal-weight "
                     "simplifications of the universe."},
    "fr": {"demo": "Mode démo : réponse scénarisée à partir des vrais chiffres des workers (sans LLM).",
           "rec": "Recommandation", "why": "Pourquoi cela convient", "check": "Vérification du profil",
           "assets": "Exemples d’actifs", "market": "Contexte de marché", "esg": "Examen ESG",
           "risks": "Ce qui pourrait mal tourner / limites",
           "fit": "Pour le profil de {name}, les groupes sectoriels qui conviennent le mieux ici sont {recs}.",
           "conflict": "La demande entre en conflit avec le profil de {name} : {target} obtient « {status} » "
                       "sur {rules}.",
           "vol": "{t} : volatilité annualisée de {vol}, baisse maximale de {mdd}.",
           "range": "{t} : volatilité annualisée de {lo} ({lot}) à {hi} ({hit}) selon les membres.",
           "mom": "{t} : momentum sur 12 mois de {m}, {trend}.",
           "rule": "{rule} : {status}, {value} pour une limite de {limit}.",
           "members": "{t} : {members}.",
           "phase": "Historiquement, en phase « {phase} », des secteurs comme {tilt} ont eu tendance à faire "
                    "relativement bien; c’est une tendance historique, pas une prévision.",
           "esg_flag": "{names} doivent faire l’objet d’un examen ESG; les preuves ne sont pas encore "
                       "disponibles dans ce prototype.",
           "limits": "Les rendements passés ne prédisent pas les rendements futurs, et les paniers sectoriels "
                     "sont des simplifications équipondérées de l’univers."},
}
STATUS_FR = {"conflict": "conflit", "flag": "signalement", "info": "information", "pass": "conforme"}
TREND_FR = {"above 200-day average": "au-dessus de la moyenne sur 200 jours",
            "below 200-day average": "sous la moyenne sur 200 jours"}


def proposed_weight(question: str) -> float | None:
    m = PERCENT.search(question)
    if m and 0 < int(m.group(1)) <= 100:
        return int(m.group(1)) / 100
    return 0.5 if BIG_SHARE.search(question) else None


def make(persona_key: str, question: str, lang: str):
    """(boss, presenter) callables for pipeline.ChatSession."""
    persona = PERSONAS[persona_key]
    tickers = {r["ticker"] for r in dr.get_universe().get("data", [])}

    def boss(prompt: str) -> dict:
        at.list_sectors()
        at.cycle_phase()
        at.fear_hope()
        targets = reviewer.extract_targets(question)
        weight = proposed_weight(question)
        for t in targets:
            (at.analyze_asset if t in tickers else at.analyze_sector)(t)
            at.stress_test_2022(t)
            at.check_suitability(t, weight)
        recs = RECOMMEND[persona_key]
        for r in recs:
            at.analyze_sector(r)
            at.sector_momentum(r)
            at.check_suitability(r)
        esg_groups = sorted({r["sector"] for r in dr.get_universe().get("data", [])
                             if r["ticker"] in persona["esg_review_tickers"]})
        for g in esg_groups:
            at.check_suitability(g)
        return {"requested_targets": targets, "recommended_sectors": recs, "conflicts_found": [],
                "reasoning_notes": "Demo mode: scripted plan (no LLM)."
                                   + (f" Assumed proposed weight {weight:.0%}." if weight else "")}

    def presenter(persona_, question_, history, trace, plan, notes, feedback=None) -> str:
        return write(trace, plan, persona, lang)

    return boss, presenter


def write(trace, plan: dict, persona: dict, lang: str) -> str:
    t = T[lang]

    def pct(x):
        s = f"{x * 100:.1f}"
        return s.replace(".", ",") + "\u00a0%" if lang == "fr" else s + "%"

    def status(s):
        return STATUS_FR.get(s, s) if lang == "fr" else s

    def latest(action, target=None):
        found = [s for s in trace.steps if s["actor"].startswith("worker:") and s["action"] == action
                 and s["output"].get("status") == "ok"
                 and (target is None or any(str(v) == target for v in (s["input"] or {}).values()))]
        return found[-1] if found else None

    recs = plan.get("recommended_sectors") or []
    lines = [f"*{t['demo']}*", "", f"**{t['rec']}**"]
    suit_recs = [latest("check_suitability", r) for r in recs]
    cite = ", ".join(str(s["step"]) for s in suit_recs if s)
    lines.append(t["fit"].format(name=persona["name"], recs=", ".join(f"**{r}**" for r in recs))
                 + (f" [fact: step {cite}]" if cite else ""))
    for target in plan.get("requested_targets") or []:
        s = latest("check_suitability", target)
        if s and s["output"]["data"]["overall"] in ("conflict", "flag"):
            d = s["output"]["data"]
            rules = ", ".join(c["rule"] for c in d["checks"] if c["status"] == d["overall"])
            lines.append(t["conflict"].format(name=persona["name"], target=target, status=status(d["overall"]),
                                              rules=rules) + f" [fact: step {s['step']}]")

    lines += ["", f"**{t['why']}**"]
    for target in list(plan.get("requested_targets") or []) + recs:
        s = latest("analyze_asset", target) or latest("analyze_sector", target)
        if not s:
            continue
        d = s["output"]["data"]
        if "range" in d:
            v = d["range"]["annualized_vol"]
            lines.append("- " + t["range"].format(t=target, lo=pct(v["min"]), lot=v["min_ticker"], hi=pct(v["max"]),
                                                 hit=v["max_ticker"]) + f" [fact: step {s['step']}]")
        else:
            lines.append("- " + t["vol"].format(t=target, vol=pct(d["annualized_vol"]), mdd=pct(d["max_drawdown"]))
                         + f" [fact: step {s['step']}]")
        m = latest("sector_momentum", target)
        basket = (m["output"]["data"].get("basket") if m else None)
        if basket:
            trend = TREND_FR.get(basket["trend"], basket["trend"]) if lang == "fr" else basket["trend"]
            lines.append("- " + t["mom"].format(t=target, m=pct(basket["momentum_12m"]), trend=trend)
                         + f" [fact: step {m['step']}]")

    lines += ["", f"**{t['check']}**"]
    for target in list(plan.get("requested_targets") or []) + recs:
        s = latest("check_suitability", target)
        if not s:
            continue
        for c in s["output"]["data"]["checks"]:
            if c["status"] not in ("conflict", "flag") or c["rule"] == "esg_review":
                continue
            value = c["value"]
            shown = (", ".join(f"{k} {pct(v)}" for k, v in value.items()) if isinstance(value, dict)
                     else pct(value) if isinstance(value, (int, float)) else "-")
            limit = pct(c["limit"]) if isinstance(c["limit"], (int, float)) else str(c["limit"])
            lines.append(f"- {target}, " + t["rule"].format(rule=c["rule"], status=status(c["status"]), value=shown,
                                                           limit=limit) + f" [fact: step {s['step']}]")

    lines += ["", f"**{t['assets']}**"]
    sectors = latest("list_sectors")
    if sectors:
        groups = sectors["output"]["data"]
        for r in recs:
            members = ", ".join(f"{m['ticker']} ({m['name']})" for m in groups.get(r, {}).get("members", []))
            if members:
                lines.append("- " + t["members"].format(t=r, members=members) + f" [fact: step {sectors['step']}]")

    cycle = latest("cycle_phase")
    if cycle:
        d = cycle["output"]["data"]
        lines += ["", f"**{t['market']}**",
                  t["phase"].format(phase=d["phase"], tilt=", ".join(d["sector_tilt"])) + " [assumption]"]

    flagged = [n for s in trace.steps if s["actor"] == "worker:suitability" and s["output"].get("status") == "ok"
               for c in s["output"]["data"]["checks"] if c["rule"] == "esg_review" and c["status"] == "flag"
               for n in c["value"]]
    if flagged:
        lines += ["", f"**{t['esg']}**", t["esg_flag"].format(names=", ".join(dict.fromkeys(flagged)))
                  + " [assumption]"]

    lines += ["", f"**{t['risks']}**", t["limits"] + " [assumption]"]
    return "\n".join(lines)
