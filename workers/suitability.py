"""suitability worker: checks a ticker or sector group against a persona's limits and preferences.

Deterministic, no LLM. Every limit in personas.py for the persona appears in the output (never skipped).
Status per rule:
  conflict       hard rule broken (excluded asset type, or proposed weight above a cap)
  flag           the target on its own breaks a portfolio-level limit (standalone vol or 2022 drawdown above the
                 persona limit) or needs review (ESG). A cap with no proposed weight is never a flag.
  info           portfolio-level reminder: a cap to respect when no weight is proposed ("keep at most 15.0%"),
                 or a minimum still to fill (e.g. bonds >= 50% alongside this target)
  pass           within the limit
  not_applicable rule does not concern this target
  not_evaluated  data missing (reason given)
Limits are team assumptions (personas.py / CLAUDE.md). Return contract: see AGENT_GUARDRAILS.md. Never raises.
"""
from personas import PERSONAS, SOURCE as PERSONA_SOURCE
from workers import data_retriever as dr
from workers import risk_analyst as ra

DEFAULT_START, DEFAULT_END = "2021-11-12", "2026-11-12"  # starter dataset window (CLAUDE.md)
SEVERITY = ["conflict", "flag", "info", "not_evaluated", "pass", "not_applicable"]


def _err(msg):
    return {"status": "error", "error": msg}


def _check(rule, limit, value, status, explanation):
    return {"rule": rule, "limit": limit, "value": value, "status": status, "explanation": explanation}


def _pct(x):
    return f"{x:.1%}"


def _target(target):
    """Resolve a ticker or sector name -> (kind, name, members[universe rows])."""
    info = dr.get_asset_info(target)
    if info["status"] == "ok":
        return "asset", target, [info["data"]]
    members = ra.sector_members(target)
    if members:
        return ra.group_kind(members), target, members
    return None, target, []


def _risk(kind, target, start, end):
    """{name: {annualized_vol, max_drawdown}} for the full window and for 2022, plus the raw results.
    The 2022 stress test is only used when 2022 ends on/before `end` (no look-ahead)."""
    full = ra.analyze_asset(target, start, end) if kind == "asset" else ra.analyze_sector(target, start, end)
    stress = (ra.stress_test_2022(target) if end >= ra.STRESS_END
              else {"status": "error", "error": f"2022 stress test needs data to {ra.STRESS_END}; analysis ends {end}"})
    out = {}
    if full["status"] == "ok":
        d = full["data"]
        rows = ({target: d} if kind in ("asset", "industry") else d["member_metrics"])
        out = {n: {"annualized_vol": m["annualized_vol"]} for n, m in rows.items()}
    if stress["status"] == "ok":
        for n, m in stress["data"].items():
            out.setdefault(n, {})["max_drawdown_2022"] = m["max_drawdown"]
    return out, full, stress


def _against_cap(rule, cap, proposed, what):
    if proposed is None:  # nothing is broken yet: a reminder of the cap, not a flag
        return _check(rule, cap, None, "info", f"{what}: keep at most {_pct(cap)} of the portfolio (no weight proposed)")
    status = "conflict" if proposed > cap else "pass"
    return _check(rule, cap, proposed, status,
                  f"{what}: proposed {_pct(proposed)} vs cap {_pct(cap)} -> {'above' if status == 'conflict' else 'within'} cap")


def _numeric_rule(rule, limit, values, key, better_low=True, fmt=_pct, label=""):
    """Compare each member's metric with the limit. values = {name: {key: x}}."""
    vals = {n: v[key] for n, v in values.items() if v.get(key) is not None}
    if not vals:
        return _check(rule, limit, None, "not_evaluated", f"{label} not available for this target")
    ok = {n: x for n, x in vals.items() if (x <= limit if better_low else x >= limit)}
    detail = ", ".join(f"{n} {fmt(x)}" for n, x in vals.items())
    if len(ok) == len(vals):
        return _check(rule, limit, vals, "pass", f"{label} {detail} within limit {fmt(limit)}")
    within = f"; within limit: {', '.join(ok)}" if ok and len(vals) > 1 else ""
    return _check(rule, limit, vals, "flag",
                  f"{label} {detail} vs persona limit {fmt(limit)}: on its own this exceeds the limit, so it could "
                  f"only be a small part of the portfolio{within}")


def check(persona: str, target: str, proposed_weight: float | None = None,
          start: str = DEFAULT_START, end: str = DEFAULT_END) -> dict:
    """Check a ticker (e.g. 'NVDA') or sector group (e.g. 'Utilities', 'Bonds') against a persona's limits.

    proposed_weight: optional fraction of the portfolio the user wants in the target (0.5 = 50%).
    Returns one check per persona limit (+ ESG review), with numbers, status and explanation, and an overall verdict.
    """
    try:
        p = PERSONAS.get(str(persona).strip().lower())
        if p is None:
            return _err(f"unknown persona '{persona}'; choose one of {sorted(PERSONAS)}")
        if proposed_weight is not None and not 0 <= proposed_weight <= 1:
            return _err("proposed_weight must be a fraction between 0 and 1")
        kind, name, members = _target(target)
        if kind is None:
            return _err(f"unknown ticker or sector '{target}'")
        classes = {m["asset_class"] for m in members}
        is_crypto = classes == {"crypto"}
        # a one-asset industry (e.g. Utilities = FTS.TO) is a single stock in practice
        is_single_stock = classes == {"equity"} and len(members) == 1
        is_bond = classes == {"etf_bond"}
        sector = members[0]["sector"] if kind == "asset" else name
        risk, full, stress = _risk(kind, target, start, end)
        warnings = list(full["warnings"]) if full["status"] == "ok" else [f"risk data: {full['error']}"]
        if stress["status"] == "ok":
            warnings += [f"2022 stress test (fixed window {stress['period']['start']} to {stress['period']['end']}): {w}"
                         for w in stress["warnings"]] or [
                f"2022 stress test uses the fixed window {stress['period']['start']} to {stress['period']['end']}"]
        else:
            warnings.append(f"2022 stress data: {stress['error']}")

        checks = []
        for rule, limit in p["limits"].items():
            if rule == "crypto_max":
                if not is_crypto:
                    checks.append(_check(rule, limit, 0.0, "pass", "target holds no crypto"))
                elif limit == 0:
                    checks.append(_check(rule, limit, proposed_weight, "conflict",
                                         f"{p['name']}'s profile excludes crypto (limit 0%)"))
                else:
                    checks.append(_against_cap(rule, limit, proposed_weight, "crypto"))
            elif rule == "single_stock_max":
                checks.append(_against_cap(rule, limit, proposed_weight, f"single stock {members[0]['ticker']}")
                              if is_single_stock
                              else _check(rule, limit, None, "not_applicable", "target is not a single stock"))
            elif rule == "sector_max":
                cap = limit.get(sector)
                checks.append(_against_cap(rule, cap, proposed_weight, f"sector {sector}") if cap is not None
                              else _check(rule, limit, None, "not_applicable", f"no cap for sector {sector}"))
            elif rule == "min_asset_classes":
                n = len(classes)
                checks.append(_check(rule, limit, n, "pass" if n >= limit else "info",
                                     f"target covers {n} asset class(es) {sorted(classes)}; the portfolio needs at "
                                     f"least {limit}, so pair it with other asset classes" if n < limit
                                     else f"target covers {n} asset classes"))
            elif rule == "vol_max":
                checks.append(_numeric_rule(rule, limit, risk, "annualized_vol",
                                            label=f"annualized vol ({start} to {end}, CAD):"))
            elif rule in ("bonds_min", "bonds_cash_min"):
                what = "bonds" if rule == "bonds_min" else "bonds/cash"
                if is_bond:
                    checks.append(_check(rule, limit, proposed_weight, "pass",
                                         f"target counts toward the {_pct(limit)} {what} minimum"))
                elif proposed_weight is not None and proposed_weight > 1 - limit:
                    checks.append(_check(rule, limit, proposed_weight, "conflict",
                                         f"proposed {_pct(proposed_weight)} leaves less than the {_pct(limit)} "
                                         f"{what} minimum for the rest of the portfolio"))
                else:
                    checks.append(_check(rule, limit, proposed_weight, "info",
                                         f"portfolio still needs at least {_pct(limit)} in {what} alongside this target"))
            elif rule == "stress_2022_max_drawdown":
                checks.append(_numeric_rule(rule, limit, risk, "max_drawdown_2022", better_low=False,
                                            label="max drawdown in 2022 (CAD):"))
            else:
                checks.append(_check(rule, limit, None, "not_evaluated", "no evaluator for this rule yet"))

        tickers = [m["ticker"] for m in members]
        review = [t for t in tickers if t in p["esg_review_tickers"]]
        if p["esg_review_tickers"]:
            checks.append(_check("esg_review", p["esg_review_tickers"], review, "flag" if review else "pass",
                                 f"ESG review needed for {review} (evidence comes from the ethics worker, "
                                 "not available yet)" if review else "no ESG-review names in target"))

        statuses = {c["status"] for c in checks}
        overall = ("conflict" if "conflict" in statuses else "flag" if "flag" in statuses
                   else "incomplete" if "not_evaluated" in statuses else "pass")
        data = {"persona": p["name"], "target": name, "target_kind": kind, "members": tickers,
                "proposed_weight": proposed_weight, "checks": checks, "overall": overall,
                "counts": {s: sum(c["status"] == s for c in checks) for s in SEVERITY}}
        src = PERSONA_SOURCE + ("; risk: " + full["source"] if full["status"] == "ok" else "")
        period = full["period"] if full["status"] == "ok" else {"start": start, "end": end}
        return {"status": "ok", "data": data, "source": src, "period": period,
                "currency": "CAD", "warnings": warnings}
    except Exception as e:
        return _err(f"suitability check failed: {e}")
