"""Presenter comparison on the REAL pipeline: the same 100 questions with presenter = Sonnet 4.6, Sonnet 5 and
Opus 5.5 (boss unchanged), then the Opus 5.5 judge on every answer. Latency, cost and judge scores per model.

Sonnet 5 and Opus 5.5 reason before writing, so they get maxTokens 6000 (the app's 1500 can end them early);
Sonnet 4.6 keeps the app's 1500. No temperature for any of them.

    python scripts/eval/compare_presenters.py --n 10      # 10 questions x 3 models, then judged
"""
import common as c

NAME = "compare_presenters"
MODELS = {
    "sonnet-4-6": ("global.anthropic.claude-sonnet-4-6", 1500),
    "sonnet-5": ("global.anthropic.claude-sonnet-5", 6000),
    "opus-5-5": ("global.anthropic.claude-opus-5-5", 6000),
}


def items(n: int) -> list[dict]:
    qs = c.questions(n, seed=100, prefix="p")
    return [{**q, "id": f"{q['id']}-{label}", "presenter": label} for q in qs for label in MODELS]


def work(item):
    model, max_tokens = MODELS[item["presenter"]]
    rec = c.run_pipeline(item, presenter_model=model, presenter_max_tokens=max_tokens)
    rec["presenter"], rec["question_id"] = item["presenter"], item["id"].rsplit("-", 1)[0].split("-")[0]
    return rec


COLUMNS = ["id", "status", "presenter", "presenter_model", "question_id", "profile", "lang", "question", "run_id",
           "total_ms", "first_text_ms", "presenter_ms", "presenter_in", "presenter_out", "cost_usd", "work_verdict",
           "answer_verdict", "answer_attempts", "numbers_flagged_first", "starts_with_summary", "guardrail_blocked", "error"]


def main():
    a = c.parse(c.base_args(__doc__, 100))
    guard = None if a.no_guardrail else c.guardrail_from_env()
    budget = c.Budget(a.budget_usd, estimate=0.25)
    c.run_pool(NAME, items(a.n), work, budget, a.concurrency, processes=True, init=c.init_worker, init_args=(guard,))
    rows = sorted(c.load(NAME).values(), key=lambda r: r["id"])
    c.write_csv(c.OUT / f"{NAME}.csv", rows, COLUMNS)
    import judge
    judge.judge_source(NAME, None, c.Budget(a.budget_usd, estimate=0.25), a.concurrency)
    import report
    report.main()
    if not a.no_upload:
        c.upload([c.OUT / f"{NAME}.csv", c.raw_path(NAME), c.OUT / "judge_compare_presenters.csv",
                  c.raw_path("judge_compare_presenters"), report.report_path()])


if __name__ == "__main__":
    main()
