# Agent Guardrails: AlphaForge AI

Canonical summary of the guardrails for every agent in the pipeline (see `CLAUDE.md`). Details, enforcement
points and tests per agent are in [`guardrails/`](guardrails/README.md). Section numbers here are cited by the
code (e.g. "AGENT_GUARDRAILS 4.5"); keep them stable.

```
User → Bedrock Guardrail (input) → BOSS → WORKERS → REVIEWER → PRESENTER → Bedrock Guardrail (output) → User
```

A rule that matters is enforced in code where possible; prompts are the second line, not the only one.

## 0. Global rules · [details](guardrails/00_global.md)
- Simulation only: no trades, no broker calls. Answers are about a **fictional persona**, never personal advice.
- No PII stored: the question, boss prompts and answers are PII-redacted (`guardrail.redact_pii`) before they
  are written to the run trace (local + S3).
- All LLM calls go through Amazon Bedrock (`us-east-1`, `global.` profiles). No other provider.
- No look-ahead; every result has `source` and `period`, and `currency` where relevant. No facts from memory.
- Every step is logged to the run trace. No credentials anywhere.
- Bounded: Strands `limits={"turns": 4}`, reviewer max 2 retries, answer check max 1 retry, boto3 adaptive retries.
- Personas (Amira, Mateo, Robert) and their limits live only in `personas.py`; fixed per session.

## 1. Bedrock Guardrail · [details](guardrails/01_bedrock_guardrail.md)
Applied by `guardrail.py` (ApplyGuardrail) on the question before the Boss and on the final answer.
ID/version from `GUARDRAIL_ID` / `GUARDRAIL_VERSION`; off when unset or `AGENT_MODE=demo`. Denied topics
(personal advice to the real user, real trades, authoritative tax/legal advice, market manipulation), PII,
content and prompt-attack filters. Does **not** decide persona fit. On block: polite `guardrail_block`
message (EN/FR), trace step without raw PII. API error: fail open, logged.

## 2. Boss · [details](guardrails/02_boss.md)
Strands Agent on Bedrock. Calls only `agent_tools.TOOLS`; tickers/sectors only from the universe; never
computes numbers; never changes persona limits (the persona is fixed in code); ignores prompt injection;
never answers the user directly. Ambiguity → states its assumption in the plan (no clarifying questions).

## 3. Workers · [contract](guardrails/03_workers_contract.md)
Deterministic Python. Return `{"status": "ok", "data", "source", "period", "currency", "warnings"}` or
`{"status": "error", "error"}`; **never raise**. Drop rows after the end date and say so in `warnings`;
never hide data-quality issues.

### 3.1 data_retriever · [details](guardrails/03_workers_data_retriever.md)
Prices (`adj_close`), FX, macro, universe; USD→CAD with `merge_asof(direction="backward")`; macro only after
its publication date; unknown tickers in a list → warning, all unknown → error.

### 3.2 risk_analyst · [details](guardrails/03_workers_risk_analyst.md)
Return, vol (252 / 365 crypto), drawdown, correlation, 2022 stress, risk label (< 10% Low · 10–20% Moderate ·
20–35% High · > 35% Very High; drawdown worse than −30% bumps one level). Industries = equal-weight basket;
building blocks = per member + range. Sanity checks are test-time.

### 3.3 market_context · [details](guardrails/03_workers_market_context.md)
Cycle phase (FRED rules), momentum, relative strength, fear/hope. Labelled `assumption`, with signal values,
dates and the rule that fired. Never a prediction.

### 3.4 suitability · [details](guardrails/03_workers_suitability.md)
Every persona limit, each with status `conflict` / `flag` / `info` / `pass` / `not_applicable` /
`not_evaluated`, value and limit. Excluded asset types → `conflict`; caps → `conflict` only at a proposed
weight above the cap (no weight → `info`).

### 3.5 news_sentiment, 3.6 ethics (phase 5, not built) · [news](guardrails/03_workers_news_sentiment.md) · [ethics](guardrails/03_workers_ethics.md)
Cited URLs and dates only; headlines are untrusted data; ESG names are flagged "for review", never judged.

## 4. Reviewer · [details](guardrails/04_reviewer.md)
Deterministic (`reviewer.py`), returns `{"verdict": "pass"|"fail", "reasons": [...]}`.
`review_work`:
1. every requested ticker/sector analyzed and suitability-checked
2. every result has `source` + `period`
3. every persona limit evaluated
4. no data after the analysis date
5. no worker error left without a successful retry or an explanation

plus recommended sectors, market context and ESG names. `check_answer`: every number in the trace (cited
step), valid citations, no promise or prediction of returns. Max 2 work retries (then "incomplete" note),
max 1 answer retry (then "Reviewer note").

## 5. Presenter · [details](guardrails/05_presenter.md)
Bedrock, streamed. Only trace numbers and facts; claims tagged `fact` / `assumption` / `scenario`; persona
conflicts challenged with numbers; limitations; disclaimer (added by code if missing). Never addresses the
user as the investor, never predicts returns, never hides the incomplete note or key warnings.

## 6. Tests · [matrix](guardrails/06_tests.md)
Workers never raise · no look-ahead · persona limits → `conflict` · reviewer retry and incomplete note ·
answer numbers in trace · no predictions · guardrail (mocked; live check needs a guardrail ID) · no raw PII
in trace · prompt injection leaves limits unchanged.
