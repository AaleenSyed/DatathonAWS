"""Benchmark on the REAL Bedrock pipeline: N questions (default 600) from templates across Amira, Mateo, Robert and
3 custom profiles (~20% French). Per run: duration, tokens per model, estimated USD, reviewer verdicts, numbers flagged.

    python scripts/eval/benchmark.py --n 10            # smoke test
    python scripts/eval/benchmark.py                   # 600, resumes where it stopped
Writes reports/eval/raw/benchmark.jsonl, reports/eval/benchmark.csv, docs/eval_report.md; uploads to S3 runs/eval/.
"""
import common as c

NAME = "benchmark"
COLUMNS = ["id", "status", "profile", "lang", "template", "question", "run_id", "boss_model", "presenter_model",
           "wall_s", "total_ms", "first_text_ms", "boss_ms", "presenter_ms", "llm_calls", "boss_in", "boss_out",
           "presenter_in", "presenter_out", "guardrail_units", "cost_usd", "work_verdict", "answer_verdict",
           "answer_attempts", "first_check", "numbers_flagged_first", "numbers_flagged_final", "recheck",
           "guardrail_blocked", "recommended", "recommends_conflict", "starts_with_summary", "throttle_retries", "error"]


def work(item):
    return c.run_pipeline(item)


def export():
    rows = sorted(c.load(NAME).values(), key=lambda r: r["id"])
    c.write_csv(c.OUT / f"{NAME}.csv", rows, COLUMNS)
    return rows


def main():
    a = c.parse(c.base_args(__doc__, 600))
    items = c.questions(a.n, seed=600, prefix="b")
    guard = None if a.no_guardrail else c.guardrail_from_env()
    c.run_pool(NAME, items, work, c.Budget(a.budget_usd, estimate=0.15), a.concurrency, processes=True,
               init=c.init_worker, init_args=(guard,))
    export()
    import report
    report.main()
    if not a.no_upload:
        c.upload([c.OUT / f"{NAME}.csv", c.raw_path(NAME), report.report_path()])


if __name__ == "__main__":
    main()
