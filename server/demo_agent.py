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
T["en"].update({
    "summary": "Summary",
    "s_conflict": "{target} conflicts with {name}'s profile: {rule}: {value} vs a limit of {limit}.",
    "s_flag": "{target} on its own is above {name}'s limits: {rule}: {value} vs a limit of {limit}.",
    "s_rec": "Recommended for {name}: **{rec}**{pair}; its main risk is an annualized volatility of {vol}.",
    "s_rec_range": "Recommended for {name}: **{rec}**{pair}; its members' annualized volatility ranges from "
                   "{lo} to {hi}.",
    "s_pair": ", paired with **{block}** as a building block",
    "s_fit": "This fits a {risk} risk tolerance and a {horizon} year horizon; past returns do not predict "
             "quick gains.",
})
T["fr"].update({
    "summary": "Résumé",
    "s_conflict": "{target} entre en conflit avec le profil de {name} : {rule} : {value} pour une limite de {limit}.",
    "s_flag": "{target} dépasse à lui seul les limites de {name} : {rule} : {value} pour une limite de {limit}.",
    "s_rec": "Recommandé pour {name} : **{rec}**{pair}; son principal risque est une volatilité annualisée "
             "de {vol}.",
    "s_rec_range": "Recommandé pour {name} : **{rec}**{pair}; la volatilité annualisée de ses membres va de "
                   "{lo} à {hi}.",
    "s_pair": ", jumelé à **{block}** comme bloc de base",
    "s_fit": "Cela convient à une tolérance au risque {risk} et à un horizon de {horizon} ans; les rendements "
             "passés ne prédisent pas des gains rapides.",
})
RISK_FR = {"low": "faible", "high": "élevée", "moderate": "modérée", "low-moderate": "faible à modérée"}
# Plain-language rule names (never show the code names in an answer)
RULE = {
    "en": {"crypto_max": "crypto cap", "single_stock_max": "single-stock cap", "sector_max": "sector cap",
           "min_asset_classes": "minimum number of asset classes", "vol_max": "volatility limit",
           "bonds_min": "bonds minimum", "bonds_cash_min": "bonds and cash minimum",
           "stress_2022_max_drawdown": "2022 drawdown limit", "esg_review": "ESG review"},
    "fr": {"crypto_max": "plafond crypto", "single_stock_max": "plafond par titre",
           "sector_max": "plafond sectoriel", "min_asset_classes": "nombre minimal de catégories d’actifs",
           "vol_max": "limite de volatilité", "bonds_min": "minimum en obligations",
           "bonds_cash_min": "minimum en obligations et encaisse", "stress_2022_max_drawdown": "limite de baisse en 2022",
           "esg_review": "examen ESG"},
}
STATUS_FR = {"conflict": "conflit", "flag": "signalement", "info": "information", "pass": "conforme"}
TREND_FR = {"above 200-day average": "au-dessus de la moyenne sur 200 jours",
            "below 200-day average": "sous la moyenne sur 200 jours"}


def proposed_weight(question: str) -> float | None:
    m = PERCENT.search(question)
    if m and 0 < int(m.group(1)) <= 100:
        return int(m.group(1)) / 100
    return 0.5 if BIG_SHARE.search(question) else None


def ranked_recommendation() -> list[str]:
    """Custom profiles have no scripted pick: the first ranked industry, plus the building block to pair with."""
    r = at.rank_sectors_for_persona()
    industries = [c["group"] for c in r.get("candidates", []) if c["kind"] == "industry"]
    return industries[:1] + ([r["pair_with"]] if r.get("pair_with") else [])


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
        recs = RECOMMEND.get(persona_key) or ranked_recommendation()
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

    def rule_name(r):
        return RULE[lang].get(r, r.replace("_", " "))

    def shown(value):
        return (", ".join(f"{k} {pct(v)}" for k, v in value.items()) if isinstance(value, dict)
                else pct(value) if isinstance(value, (int, float)) else "-")

    def limit_s(limit):
        return pct(limit) if isinstance(limit, (int, float)) else str(limit)

    def latest(action, target=None):
        found = [s for s in trace.steps if s["actor"].startswith("worker:") and s["action"] == action
                 and s["output"].get("status") == "ok"
                 and (target is None or any(str(v) == target for v in (s["input"] or {}).values()))]
        return found[-1] if found else None

    recs = plan.get("recommended_sectors") or []
    name = persona["name"]

    # ---- Summary: at most 3 bullets (conflict first, recommendation + one risk number, fit) ----
    summary = []
    for target in plan.get("requested_targets") or []:
        s = latest("check_suitability", target)
        d = s["output"]["data"] if s else {}
        if d.get("overall") in ("conflict", "flag"):
            c = next((c for c in d["checks"] if c["status"] == d["overall"] and c["rule"] != "esg_review"), None)
            if c:
                summary.append(t[f"s_{d['overall']}"].format(target=target, name=name, rule=rule_name(c["rule"]),
                                                             value=shown(c["value"]), limit=limit_s(c["limit"]))
                               + f" [fact: step {s['step']}]")
                break
    sector_steps = {r: latest("analyze_sector", r) for r in recs}
    blocks = [r for r, s in sector_steps.items() if s and "range" in s["output"]["data"]]
    main = next((r for r in recs if r not in blocks), recs[0] if recs else None)
    if main and sector_steps.get(main):
        a = sector_steps[main]
        d = a["output"]["data"]
        block = next((b for b in blocks if b != main), None)
        pair = t["s_pair"].format(block=block) if block else ""
        cites = [a["step"]] + [s["step"] for r in recs if (s := latest("check_suitability", r))]
        if "range" in d:
            v = d["range"]["annualized_vol"]
            text = t["s_rec_range"].format(name=name, rec=main, pair=pair, lo=pct(v["min"]), hi=pct(v["max"]))
        else:
            text = t["s_rec"].format(name=name, rec=main, pair=pair, vol=pct(d["annualized_vol"]))
        summary.append(text + f" [fact: step {', '.join(map(str, dict.fromkeys(cites)))}]")
    user = next((s for s in trace.steps if s["actor"] == "user"), None)
    risk = RISK_FR.get(persona["risk_tolerance"], persona["risk_tolerance"]) if lang == "fr" else persona["risk_tolerance"]
    summary.append(t["s_fit"].format(risk=risk, horizon=persona["horizon_years"])
                   + (f" [fact: step {user['step']}]" if user else " [assumption]"))

    lines = [f"*{t['demo']}*", "", f"## {t['summary']}"] + [f"- {x}" for x in summary[:3]]
    lines += ["", f"**{t['rec']}**"]
    suit_recs = [latest("check_suitability", r) for r in recs]
    cite = ", ".join(str(s["step"]) for s in suit_recs if s)
    lines.append(t["fit"].format(name=name, recs=", ".join(f"**{r}**" for r in recs))
                 + (f" [fact: step {cite}]" if cite else ""))
    for target in plan.get("requested_targets") or []:
        s = latest("check_suitability", target)
        if s and s["output"]["data"]["overall"] in ("conflict", "flag"):
            d = s["output"]["data"]
            rules = ", ".join(rule_name(c["rule"]) for c in d["checks"] if c["status"] == d["overall"])
            lines.append(t["conflict"].format(name=name, target=target, status=status(d["overall"]),
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
            lines.append(f"- {target}, " + t["rule"].format(rule=rule_name(c["rule"]), status=status(c["status"]),
                                                           value=shown(c["value"]), limit=limit_s(c["limit"]))
                         + f" [fact: step {s['step']}]")

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

    flagged = [n for s in trace.steps if s["action"] == "check_suitability" and s["output"].get("status") == "ok"
               for c in s["output"]["data"]["checks"] if c["rule"] == "esg_review" and c["status"] == "flag"
               for n in c["value"]]
    if flagged:
        lines += ["", f"**{t['esg']}**", t["esg_flag"].format(names=", ".join(dict.fromkeys(flagged)))
                  + " [assumption]"]

    lines += ["", f"**{t['risks']}**", t["limits"] + " [assumption]"]
    return "\n".join(lines)
