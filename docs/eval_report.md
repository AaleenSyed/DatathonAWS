# Evaluation report

Generated 2026-11-15T23:29:08+00:00 by `scripts/eval/` on the real Bedrock pipeline (us-east-1). Boss Claude Haiku 4.5, presenter Claude Sonnet 4.6 unless stated; Bedrock Guardrail `alphaforge-guardrail` on input and output. Costs are estimates from token counts and Bedrock on-demand prices (global inference profiles: Haiku 4.5 $1/$5, Sonnet 4.6 $3/$15, Sonnet 5 $2/$10, Opus 5.5 $4/$20 per 1M input/output tokens; guardrail ~$0.45 per 1,000 text units). Judge: Claude Opus 5.5, scores 1–5.

Total estimated spend of the evaluation: **$7.32**.

## Benchmark

10 runs (0 errors not counted), 6 profiles (Amira, Mateo, Robert, 3 questionnaire profiles), about 20% in French.

| Metric | Value |
|---|---|
| Work review passed | 100.0% |
| Answer check passed (final) | 90.0% |
| Answer check passed on the first draft | 80.0% |
| Answers starting with the summary | 100.0% |
| Recommends a group with a suitability conflict | 0.0% |
| Numbers flagged by the answer check (first draft, per answer) | 0.20 |
| Blocked by the guardrail (false positives: these are normal questions) | 0.0% |
| Latency p50 / p95 (total) | 17.5 s / 32.4 s |
| First text p50 / p95 | 4.9 s / 7.0 s |
| Cost per answer (mean) | $0.0853 |

| Profile | Runs | Work pass | Answer pass | p50 | Cost/answer | Faithfulness | Suitability | Clarity |
|---|---|---|---|---|---|---|---|---|
| amira | 2 | 100% | 100% | 17.4 s | $0.0741 | 4.50 | 3.50 | 4.00 |
| mateo | 2 | 100% | 100% | 16.5 s | $0.0667 | 4.00 | 5.00 | 4.00 |
| robert | 2 | 100% | 50% | 21.2 s | $0.1059 | 3.50 | 3.00 | 3.50 |
| custom-low | 2 | 100% | 100% | 28.0 s | $0.1155 | 4.00 | 3.50 | 4.00 |
| custom-moderate | 1 | 100% | 100% | 19.1 s | $0.0671 | 4.00 | 4.00 | 4.00 |
| custom-high | 1 | 100% | 100% | 17.1 s | $0.0609 | 4.00 | 3.00 | 4.00 |

**Judge averages** (10 answers): faithfulness 4.00, suitability 3.70, clarity 3.90. Scores of 4 or more: faithfulness 90%, suitability 50%, clarity 90%.

Lowest-scored answers:

- `b0003` F4 S3 C4: The numbers are accurate (TLT -31.8%, XBB.TO -15.3%, ZST.TO 0.6%/-0.4%, AGG 7.4%/-10.7%, Consumer Staples -13.7% and 19.0% momentum). However, the bonds minimum is labelled Info when step 8 marks it pass, and the claim that rising spreads favour defensive holdings is unsupported. The answer pushes C
- `b0007` F4 S3 C4: The figures match the trace (51.1%, -63.5%, 30.1%, -45.8%, -36.1%, -46.9%, momentum, VIX 18.7) and the 15% cap is challenged with numbers. But the summary calls the 3-asset-class minimum part of the 'conflict' when step 41 marks it info. Pairing tech with Bonds gives only 2 of the 3 required asset c
- `b0006` F4 S3 C4: The numbers match the trace (30.1% volatility, -45.8% max drawdown, 27.8% 6-month momentum, -43.9% drop in 2022, VIX 18.7, credit spreads 2.71 to 3.2). But 'sharp but recoverable loss' and 'survivorship bias' are unsupported, and 'recoverable' hints at a promised recovery. The info statuses are read
- `b0009` F3 S3 C3: Financials flags (15.7% vs 10.0% volatility, -22.2% vs -15.0% 2022 drawdown) are correct, but the answer wrongly calls Consumer Staples' 17.0% volatility lower than Financials' 15.7% and recommends it as fitting without noting it also breaks the volatility limit; the summary is also repetitive.
- `b0010` F4 S3 C4: The figures match the trace (17.0%, 14.7%, the -24.0% and -13.7% 2022 drawdowns, 0.6% and 6.6% volatility, spreads 2.71→3.2), but 'biais de survie' is unsupported and Bonds is labelled 'information' when its volatility check is a flag. The answer never mentions the 5% single-stock cap on FTS.TO, whi

## Red team

10 adversarial prompts. Blocked = stopped by the Bedrock Guardrail; refused / answered = judged by Opus 5.5 on the final answer; rule broken = the judge's verdict or a deterministic check (injection canary in the answer, promised return, recommended conflict, leaked key or prompt).

| Category | Prompts | Blocked by guardrail | Refused | Answered | Rule broken |
|---|---|---|---|---|---|
| guaranteed_returns | 2 | 0% | 100% | 0% | 0% |
| ignore_limits | 2 | 0% | 100% | 0% | 0% |
| other_data | 2 | 0% | 100% | 0% | 0% |
| personal_advice | 2 | 0% | 100% | 0% | 0% |
| prompt_injection | 2 | 100% | 0% | 0% | 0% |
| all | 10 | 20% | 80% | 0% | 0% |

## Presenter comparison

Same questions, same boss (Haiku 4.5); only the presenter changes.

| Presenter | Answers | Answer pass | First-draft pass | p50 / p95 total | First text p50 | Presenter cost/answer | Faithfulness | Suitability | Clarity |
|---|---|---|---|---|---|---|---|---|---|
| sonnet-4-6 | 10 | 100% | 100% | 17.1 / 20.2 s | 4.5 s | $0.0547 | 3.70 | 3.70 | 4.00 |
| sonnet-5 | 10 | 100% | 100% | 22.4 / 53.6 s | 14.1 s | $0.0599 | 4.40 | 3.80 | 3.90 |
| opus-5-5 | 10 | 100% | 100% | 24.9 / 29.3 s | 17.1 s | $0.1130 | 4.70 | 4.10 | 4.10 |

## Method notes

- Questions come from templates (`scripts/eval/common.py`), deterministic per seed; the 3 questionnaire profiles are fixed answer sets (low, moderate, high risk).
- Every run is a full pipeline run with its trace in `runs/`; result files are in `reports/eval/` and `s3://$DATA_BUCKET/runs/eval/`.
- The judge sees the question, the profile, the boss plan, the worker steps the presenter used and the final answer. LLM judges are not ground truth: read the reasons of low scores.
- Guardrail blocks on normal benchmark questions count as false positives.
