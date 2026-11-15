"""Write a readable .txt report of every worker metric for one or more persona + target cases.

Usage (from the repo root, venv active):
  PYTHONPATH=. python scripts/inspect_target.py                    # the 3 demo cases
  PYTHONPATH=. python scripts/inspect_target.py robert NVDA 0.5    # one case (weight optional)
  PYTHONPATH=. python scripts/inspect_target.py mateo Energy --out reports/mateo.txt
Default output: reports/inspect_<date>_<time>.txt
"""
import argparse
import os
import textwrap
from datetime import datetime

from workers import market_context as mc, risk_analyst as ra, suitability as su

START, END = su.DEFAULT_START, su.DEFAULT_END
WIDTH = 100
DEMO = [("robert", "NVDA", 0.5), ("amira", "Information Technology", 0.4), ("mateo", "Energy", None)]

LEGEND = [
    ("Total", "total return: price change over the whole period, dividends included (adj_close)"),
    ("Ann. ret", "annualized return: total return converted to a yearly rate"),
    ("Ann. vol", "annualized volatility: how much daily prices swing "
                 "(daily std x sqrt(252); crypto x sqrt(365))"),
    ("Max DD", "max drawdown: worst fall from a previous peak during the period"),
    ("vs peak", "current drawdown: how far the latest price is below the highest price of the period"),
    ("Label", "risk label from vol: <10% Low, 10-20% Moderate, 20-35% High, >35% Very High; "
                   "one level higher if max drawdown is worse than -30%"),
    ("Mom. 6m / 12m", "momentum: price change over the last 6 / 12 months"),
    ("vs bench 12m", "relative strength: 12-month return minus the benchmark's (SPY for U.S., XIU.TO for Canada)"),
    ("vs 200d avg", "latest price compared with its 200-day average (positive = uptrend)"),
    ("vs 12m high", "how far the latest price is below its 12-month high"),
    ("Status", "CONFLICT = rule broken; FLAG = exceeds a limit on its own or needs review; "
               "INFO = portfolio-level reminder; PASS = within limit; N/A = rule does not apply"),
]


class Doc:
    """Collects lines of text, then writes them to a file."""

    def __init__(self):
        self.lines = []

    def add(self, text="", indent=0):
        pad = " " * indent
        if not text:
            self.lines.append("")
            return
        self.lines.extend(textwrap.wrap(text, WIDTH, initial_indent=pad, subsequent_indent=pad + "  ")
                          or [pad])

    def title(self, text):
        self.lines += ["", "=" * WIDTH, text.upper().center(WIDTH).rstrip(), "=" * WIDTH]

    def section(self, text):
        self.lines += ["", text, "-" * len(text)]

    def table(self, headers, rows, indent=2):
        rows = [[str(c) for c in r] for r in rows]
        widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
        pad = " " * indent
        fmt = lambda cells: (pad + " | ".join(c.ljust(w) for c, w in zip(cells, widths))).rstrip()
        self.lines += [fmt(headers), pad + "-+-".join("-" * w for w in widths)] + [fmt(r) for r in rows]

    def save(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines).rstrip() + "\n")


def pct(x):
    return "n/a" if x is None else f"{x:+.1%}"


def vol(x):
    return "n/a" if x is None else f"{x:.1%}"


def show_value(v):
    if isinstance(v, dict):
        return ", ".join(f"{k} {pct(x) if x < 0 else vol(x)}" for k, x in v.items())
    if isinstance(v, float):
        return vol(v)
    if isinstance(v, list):
        return ", ".join(v) or "none"
    return "-" if v is None else str(v)


def risk_rows(d, kind):
    rows = []
    if kind in ("asset", "industry"):
        name = d.get("ticker") or f"{d['sector']} basket"
        rows.append((name, pct(d["total_return"]), pct(d["annualized_return"]), vol(d["annualized_vol"]),
                     pct(d["max_drawdown"]), pct(d["current_drawdown"]), d["risk_label"]))
    for t, m in d.get("member_metrics", {}).items():
        rows.append(("  " + t if kind == "industry" else t, pct(m["total_return"]), pct(m["annualized_return"]),
                     vol(m["annualized_vol"]), pct(m["max_drawdown"]), pct(m["current_drawdown"]), m["risk_label"]))
    return rows


def market(doc):
    doc.title(f"Market context as of {END}")
    doc.add("Historical tendencies, NOT predictions. Monthly series are used only from their assumed "
            "publication date (reference month + 21 days).")
    cy = mc.cycle_phase(END)["data"]
    doc.section(f"Business-cycle phase: {cy['phase']}")
    doc.add(f"Rule fired: {cy['rule_fired']}", 2)
    doc.add()
    doc.table(["Signal", "Value", "Reference date", "Usable from"],
              [(k, v["value"], v["date"], v["available_date"]) for k, v in cy["signals"].items()])
    doc.add()
    doc.add(f"Sector tilt: {', '.join(cy['sector_tilt'])}", 2)
    fh = mc.fear_hope(END)["data"]
    cs, cons, vix = fh["credit_spread"], fh["consumer_sentiment"], fh["vix"]
    doc.section(f"Fear vs hope: {fh['mood']}")
    doc.table(["Signal", "Value", "Date", "Reading"], [
        ("VIX", vix["value"], vix["date"], f"{vix['mood']} (<15 calm, 15-25 normal, >25 fear)"),
        ("High-yield credit spread", f"{cs['value']}%", cs["date"],
         f"{cs['change_3m']:+.2f} pts vs {cs['date_3m_earlier']} -> "
         + ("rising, stress signal" if cs["rising_stress"] else "not rising")),
        ("Consumer sentiment", cons["value"], cons["date"], f"12-month change {cons['change_12m']:+.1f}"),
    ])


def report(doc, persona, target, weight):
    """Append one case to doc and return its overall verdict (or 'ERROR')."""
    w = f"{weight:.0%} proposed" if weight is not None else "no weight proposed"
    doc.title(f"{persona} | {target} | {w}")

    is_asset = ra.sector_members(target) == []
    full = ra.analyze_asset(target, START, END) if is_asset else ra.analyze_sector(target, START, END)
    if full["status"] != "ok":
        doc.add(f"ERROR: {full['error']}", 2)
        return "ERROR"
    d = full["data"]
    kind = "asset" if is_asset else d["kind"]

    doc.section(f"1) Risk over the full window ({full['period']['start']} to {full['period']['end']}, "
                f"{full['currency']})")
    if kind == "building_block":
        doc.add("Building block: members shown separately, no blended figure.", 2)
    doc.table(["Asset", "Total", "Ann. ret", "Ann. vol", "Max DD", "vs peak", "Label"],
              risk_rows(d, kind))
    if kind != "building_block":
        doc.add()
        doc.add(f"Label reason: {d['risk_label_reason']}", 2)
    if "listing_currency_vol" in d:
        lc = d["listing_currency_vol"]
        doc.add(f"Vol in {lc['currency']}: {vol(lc['annualized_vol'])} "
                f"(exchange-rate effect on vol: {pct(lc['fx_effect'])})", 2)

    st = ra.stress_test_2022(target)
    doc.section(f"2) 2022 stress test ({st['period']['start']} to {st['period']['end']}, CAD)")
    doc.table(["Asset", "2022 return", "2022 max DD", "2022 vol", "Label"],
              [(t, pct(m["total_return"]), pct(m["max_drawdown"]), vol(m["annualized_vol"]), m["risk_label"])
               for t, m in st["data"].items()])

    mo = mc.sector_momentum(target, END)
    doc.section(f"3) Momentum and trend (as of {END}, CAD)")
    if mo["status"] == "ok":
        doc.table(["Asset", "Bench.", "Mom. 6m", "Mom. 12m", "vs bench 12m", "vs 200d avg", "vs 12m high",
                   "Trend"],
                  [(t, m["benchmark"], pct(m["momentum_6m"]), pct(m["momentum_12m"]),
                    pct(m["relative_strength_12m"]), pct(m["price_vs_200d_avg"]),
                    pct(m["drawdown_from_12m_high"]), m["trend"].replace(" 200-day average", " 200d"))
                   for t, m in mo["data"]["members"].items()])
    else:
        doc.add(f"ERROR: {mo['error']}", 2)

    s = su.check(persona, target, weight)
    doc.section(f"4) Suitability for {persona.capitalize()}")
    if s["status"] != "ok":
        doc.add(f"ERROR: {s['error']}", 2)
        return "ERROR"
    sd = s["data"]
    doc.table(["Rule", "Limit", "Value", "Status"],
              [(c["rule"], show_value(c["limit"]), show_value(c["value"]), c["status"].upper().replace("NOT_APPLICABLE", "N/A").replace("NOT_EVALUATED", "NOT EVAL."))
               for c in sd["checks"]])
    doc.add()
    doc.add("Why:", 2)
    for c in sd["checks"]:
        doc.add(f"- {c['rule']}: {c['explanation']}", 2)
    doc.add()
    counts = ", ".join(f"{k} {v}" for k, v in sd["counts"].items() if v)
    doc.add(f">>> OVERALL VERDICT: {sd['overall'].upper()}   ({counts})", 2)

    doc.section("5) Sources and warnings")
    doc.add(f"Source: {full['source']}", 2)
    warnings = sorted(set(full["warnings"] + s["warnings"]))
    for msg in warnings:
        doc.add(f"Warning: {msg}", 2)
    if not warnings:
        doc.add("No warnings.", 2)
    return sd["overall"].upper()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("persona", nargs="?")
    ap.add_argument("target", nargs="?")
    ap.add_argument("weight", nargs="?", type=float)
    ap.add_argument("--out", default=f"reports/inspect_{datetime.now():%Y%m%d_%H%M%S}.txt")
    a = ap.parse_args()
    cases = [(a.persona, a.target, a.weight)] if a.persona and a.target else DEMO

    body = Doc()
    market(body)
    verdicts = [(c, report(body, *c)) for c in cases]

    doc = Doc()
    doc.lines += ["=" * WIDTH, "ALPHAFORGE AI - WORKER METRICS REPORT".center(WIDTH).rstrip(), "=" * WIDTH]
    doc.add(f"Generated:  {datetime.now():%Y-%m-%d %H:%M}")
    doc.add(f"Window:     {START} to {END}")
    doc.add("Currency:   CAD (USD assets converted with Bank of Canada FX)")
    doc.add("Note:       simulation for fictional personas only, not financial advice")
    doc.section("Summary")
    doc.table(["Persona", "Target", "Proposed weight", "Verdict"],
              [(p.capitalize(), t, f"{w:.0%}" if w is not None else "-", v) for (p, t, w), v in verdicts])
    doc.section("What each metric means")
    for name, text in LEGEND:
        doc.lines += textwrap.wrap(text, WIDTH, initial_indent=f"  {name:<17} ", subsequent_indent=" " * 20)
    doc.lines += body.lines
    doc.lines += ["", "=" * WIDTH, "END OF REPORT".center(WIDTH).rstrip(), "=" * WIDTH]
    doc.save(a.out)
    print(f"Report written to {os.path.abspath(a.out)}")


if __name__ == "__main__":
    main()
