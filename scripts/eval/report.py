"""docs/eval_report.md from the eval result files (reports/eval/raw/*.jsonl). Run by every eval script."""
from collections import defaultdict
from statistics import mean

import common as c


def _ok(name):
    return [r for r in c.load(name).values() if r.get("status") == "ok"]


def _f(x, d=1, suffix=""):
    return "—" if x is None else f"{x:.{d}f}{suffix}"


def _rate(rows, pred):
    return 100 * sum(1 for r in rows if pred(r)) / len(rows) if rows else None


def _lat(rows):
    t = [r["total_ms"] / 1000 for r in rows if r.get("total_ms")]
    f = [r["first_text_ms"] / 1000 for r in rows if r.get("first_text_ms")]
    return c.pct(t, .5), c.pct(t, .95), c.pct(f, .5), c.pct(f, .95)


def _judge(name):
    return {r["id"]: r for r in _ok(name)}


def main():
    lines = ["# Evaluation report", "",
             f"Generated {c.now()} by `scripts/eval/` on the real Bedrock pipeline (us-east-1). Boss Claude Haiku 4.5, "
             "presenter Claude Sonnet 4.6 unless stated; Bedrock Guardrail `alphaforge-guardrail` on input and output. "
             "Costs are estimates from token counts and Bedrock on-demand prices (global inference profiles: Haiku 4.5 "
             "$1/$5, Sonnet 4.6 $3/$15, Sonnet 5 $2/$10, Opus 5.5 $4/$20 per 1M input/output tokens; guardrail ~$0.45 "
             "per 1,000 text units). Judge: Claude Opus 5.5, scores 1–5.", ""]
    spent = c.total_spend()
    lines += [f"Total estimated spend of the evaluation: **${spent:.2f}**.", ""]

    b = _ok("benchmark")
    errors = [r for r in c.load("benchmark").values() if r.get("status") != "ok"]
    if b:
        jb = _judge("judge_benchmark")
        p50, p95, f50, f95 = _lat(b)
        answered = [r for r in b if not r.get("guardrail_blocked")]
        lines += ["## Benchmark", "",
                  f"{len(b)} runs ({len(errors)} errors not counted), 6 profiles (Amira, Mateo, Robert, 3 questionnaire "
                  "profiles), about 20% in French.", "",
                  "| Metric | Value |", "|---|---|",
                  f"| Work review passed | {_f(_rate(answered, lambda r: r['work_verdict'] == 'pass'), 1, '%')} |",
                  f"| Answer check passed (final) | {_f(_rate(answered, lambda r: r['answer_verdict'] == 'pass'), 1, '%')} |",
                  f"| Answer check passed on the first draft | {_f(_rate(answered, lambda r: r['first_check'] == 'pass'), 1, '%')} |",
                  f"| Answers starting with the summary | {_f(_rate(answered, lambda r: r['starts_with_summary']), 1, '%')} |",
                  f"| Recommends a group with a suitability conflict | {_f(_rate(answered, lambda r: r['recommends_conflict']), 1, '%')} |",
                  f"| Numbers flagged by the answer check (first draft, per answer) | {_f(mean(r['numbers_flagged_first'] for r in answered) if answered else None, 2)} |",
                  f"| Blocked by the guardrail (false positives: these are normal questions) | {_f(_rate(b, lambda r: r.get('guardrail_blocked')), 1, '%')} |",
                  f"| Latency p50 / p95 (total) | {_f(p50, 1, ' s')} / {_f(p95, 1, ' s')} |",
                  f"| First text p50 / p95 | {_f(f50, 1, ' s')} / {_f(f95, 1, ' s')} |",
                  f"| Cost per answer (mean) | ${_f(mean(r['cost_usd'] for r in b), 4)} |",
                  ""]
        by = defaultdict(list)
        for r in answered:
            by[r["profile"]].append(r)
        lines += ["| Profile | Runs | Work pass | Answer pass | p50 | Cost/answer | Faithfulness | Suitability | Clarity |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for prof in c.PROFILES:
            rows = by.get(prof, [])
            if not rows:
                continue
            js = [jb[r["id"]] for r in rows if r["id"] in jb]
            lines.append(f"| {prof} | {len(rows)} | {_f(_rate(rows, lambda r: r['work_verdict'] == 'pass'), 0, '%')} | "
                         f"{_f(_rate(rows, lambda r: r['answer_verdict'] == 'pass'), 0, '%')} | {_f(_lat(rows)[0], 1, ' s')} | "
                         f"${_f(mean(r['cost_usd'] for r in rows), 4)} | "
                         + " | ".join(_f(mean(j[k] for j in js) if js else None, 2) for k in ("faithfulness", "suitability", "clarity")) + " |")
        if jb:
            js = list(jb.values())
            low = sorted(js, key=lambda j: min(j["faithfulness"], j["suitability"], j["clarity"]))[:5]
            lines += ["", f"**Judge averages** ({len(js)} answers): faithfulness {_f(mean(j['faithfulness'] for j in js), 2)}, "
                          f"suitability {_f(mean(j['suitability'] for j in js), 2)}, clarity {_f(mean(j['clarity'] for j in js), 2)}. "
                          f"Scores of 4 or more: faithfulness {_f(_rate(js, lambda j: j['faithfulness'] >= 4), 0, '%')}, "
                          f"suitability {_f(_rate(js, lambda j: j['suitability'] >= 4), 0, '%')}, "
                          f"clarity {_f(_rate(js, lambda j: j['clarity'] >= 4), 0, '%')}.", "",
                      "Lowest-scored answers:", ""]
            lines += [f"- `{j['id']}` F{j['faithfulness']} S{j['suitability']} C{j['clarity']}: {j['reason']}" for j in low]
        lines.append("")

    rt = _ok("redteam")
    if rt:
        lines += ["## Red team", "",
                  f"{len(rt)} adversarial prompts. Blocked = stopped by the Bedrock Guardrail; refused / answered = judged by "
                  "Opus 5.5 on the final answer; rule broken = the judge's verdict or a deterministic check (injection "
                  "canary in the answer, promised return, recommended conflict, leaked key or prompt).", "",
                  "| Category | Prompts | Blocked by guardrail | Refused | Answered | Rule broken |", "|---|---|---|---|---|---|"]
        by = defaultdict(list)
        for r in rt:
            by[r["category"]].append(r)
        for cat, rows in [*sorted(by.items()), ("all", rt)]:
            lines.append(f"| {cat} | {len(rows)} | {_f(_rate(rows, lambda r: r.get('guardrail_blocked')), 0, '%')} | "
                         f"{_f(_rate(rows, lambda r: r.get('outcome') == 'refused'), 0, '%')} | "
                         f"{_f(_rate(rows, lambda r: r.get('outcome') == 'answered'), 0, '%')} | "
                         f"{_f(_rate(rows, lambda r: r.get('broke_rule_any')), 0, '%')} |")
        broke = [r for r in rt if r.get("broke_rule_any")]
        if broke:
            lines += ["", "Rule breaks:", ""]
            lines += [f"- `{r['id']}` {r['category']}: {r.get('judge_rule') or ''} "
                      f"{'[canary] ' if r.get('injection_canary') else ''}{'[promise] ' if r.get('promise') else ''}"
                      f"{'[conflict] ' if r.get('conflict_rec') else ''}{'[leak] ' if r.get('leak') else ''}— "
                      f"{r.get('judge_reason', '')}" for r in broke[:15]]
        lines.append("")

    cp = _ok("compare_presenters")
    if cp:
        jc = _judge("judge_compare_presenters")
        lines += ["## Presenter comparison", "",
                  "Same questions, same boss (Haiku 4.5); only the presenter changes.", "",
                  "| Presenter | Answers | Answer pass | First-draft pass | p50 / p95 total | First text p50 | Presenter cost/answer | "
                  "Faithfulness | Suitability | Clarity |", "|---|---|---|---|---|---|---|---|---|---|"]
        import compare_presenters as cpm
        for label, (model, _) in cpm.MODELS.items():
            rows = [r for r in cp if r.get("presenter") == label and not r.get("guardrail_blocked")]
            if not rows:
                continue
            p50, p95, f50, _ = _lat(rows)
            js = [jc[r["id"]] for r in rows if r["id"] in jc]
            pres_cost = mean(c.usd(model, r["presenter_in"], r["presenter_out"]) for r in rows)
            lines.append(f"| {label} | {len(rows)} | {_f(_rate(rows, lambda r: r['answer_verdict'] == 'pass'), 0, '%')} | "
                         f"{_f(_rate(rows, lambda r: r['first_check'] == 'pass'), 0, '%')} | {_f(p50, 1)} / {_f(p95, 1)} s | "
                         f"{_f(f50, 1, ' s')} | ${_f(pres_cost, 4)} | "
                         + " | ".join(_f(mean(j[k] for j in js) if js else None, 2) for k in ("faithfulness", "suitability", "clarity")) + " |")
        lines.append("")

    lines += ["## Method notes", "",
              "- Questions come from templates (`scripts/eval/common.py`), deterministic per seed; the 3 questionnaire "
              "profiles are fixed answer sets (low, moderate, high risk).",
              "- Every run is a full pipeline run with its trace in `runs/`; result files are in `reports/eval/` and "
              "`s3://$DATA_BUCKET/runs/eval/`.",
              "- The judge sees the question, the profile, the boss plan, the worker steps the presenter used and the final "
              "answer. LLM judges are not ground truth: read the reasons of low scores.",
              "- Guardrail blocks on normal benchmark questions count as false positives."]
    c.DOCS.mkdir(exist_ok=True)
    (c.DOCS / "eval_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {c.DOCS / 'eval_report.md'}")


if __name__ == "__main__":
    main()
