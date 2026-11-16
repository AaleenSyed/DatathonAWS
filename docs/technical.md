# AlphaForge AI — Technical documentation

*PolyFinances Datathon 2026 · AlphaForge AI challenge on AWS*

> Educational simulation for fictional personas. Not personalized financial advice. No real transactions.

Related documents: [README](../README.md) (how to run it, full assumptions) ·
[AWS architecture](architecture-aws.en.md) · [One-pager](one-pager.en.md) ·
[Evaluation report](eval_report.md) · [Agent rules](../AGENT_GUARDRAILS.md)

---

## 1. Problem and goal

AI investing assistants usually sound confident but cannot be checked: the numbers may be invented, the answer
ignores the investor's profile, and a risky request often gets an easy "yes".

AlphaForge is a decision-support chatbot that **explains and proves every conclusion**. The user picks a fictional
persona (Amira, Mateo or Robert) or builds a fictional profile with 7 multiple-choice questions, then asks questions
in English or Canadian French. Each answer:

- recommends **a specific sector group** that fits the profile, with example assets;
- gives the risk numbers behind it (return, volatility, max drawdown, 2022 stress test), each with its source,
  period and currency;
- checks the request against the profile's limits and **says no, with numbers**, when it doesn't fit;
- links every claim to the step of the run trace that produced it.

## 2. Design principles

1. **The LLMs never calculate.** All the math is in plain Python workers with unit tests. Bedrock models only
   plan (which tools to call, what to recommend) and write.
2. **Every number is traceable.** A deterministic reviewer rejects any answer that contains a number not found in
   the worker step it cites.
3. **Suitability is a rule, not a vibe.** Persona limits are encoded in `personas.py` and checked rule by rule by
   the suitability worker. A sector with a conflict can never be recommended.
4. **Full audit trail.** Every run writes a trace (actor, input, output, timing, verdicts) to Amazon S3.
5. **Fast enough for a chat.** A summary-first, streamed answer: first text in about 5 s.

## 3. Architecture

```
Browser (React, EN/FR)
  │  WebSocket / REST (contract v0.3.0: contracts/openapi + asyncapi)
  ▼
FastAPI backend (server/)
  ▼
Bedrock Guardrail ── input check (denied topics, PII, content, prompt attack)
  ▼
BOSS ── Claude Haiku 4.5 on Bedrock (Strands agent, Converse API)
  │      calls every tool it needs in one parallel turn, returns a plan
  ▼
WORKERS ── deterministic Python, no LLM
  │      data_retriever · risk_analyst · market_context · suitability
  ▼
REVIEWER (work) ── coverage, sources, periods, limits, no look-ahead → back to boss (max 2)
  ▼
PRESENTER ── Claude Sonnet 4.6 on Bedrock (ConverseStream), streamed, summary first
  ▼
REVIEWER (answer) ── every number must exist in the cited step → 1 rewrite max
  ▼
Bedrock Guardrail ── output check
  ▼
Answer + explanation panel + run trace (local and s3://$DATA_BUCKET/runs/)
```

The diagram and the service-by-service description are in [architecture-aws.en.md](architecture-aws.en.md).

### 3.1 AWS services

| Service | Role | Code |
|---|---|---|
| Amazon Bedrock, Converse (via Strands) | Boss agent, Claude Haiku 4.5 (`global.` inference profile) | `agent_tools.py`, `pipeline.py` |
| Amazon Bedrock, ConverseStream | Presenter, Claude Sonnet 4.6, streamed to the browser | `presenter.py` |
| Amazon Bedrock Guardrails, ApplyGuardrail | Input and output filter; PII redacted before anything is written to the trace | `guardrail.py` |
| Amazon S3 | Data files (`data/`) and the full trace of every run (`runs/`), plus evaluation results (`runs/eval/`) | `workers/data_retriever.py`, `run_trace.py`, `scripts/eval/` |

Region `us-east-1`. No other model provider is called; credentials come from the environment, never from the repo.

### 3.2 Components

| Component | Responsibility |
|---|---|
| `personas.py` | Fictional personas and their limits (team assumptions) |
| `profile_builder.py` | Turns the 7-question questionnaire into a fictional profile with limits (no LLM, no personal data) |
| `workers/data_retriever.py` | Prices (`adj_close`, converted to CAD), FX, macro series with publication lag |
| `workers/risk_analyst.py` | Return, volatility, max drawdown, correlation, 2022 stress test, risk label, per asset and per sector |
| `workers/market_context.py` | Business-cycle phase (FRED rules), fear vs hope, momentum and relative strength |
| `workers/suitability.py` | Checks a ticker or sector against the profile: `pass` / `info` / `flag` / `conflict` per rule |
| `agent_tools.py` | Workers exposed as Strands tools. Coarse tools (`assess_target`, `rank_sectors_for_persona`, `market_snapshot`) return compact results to the boss; the trace keeps the full output |
| `reviewer.py` | Deterministic checks of the work and of the final answer |
| `presenter.py` | Streamed answer with claim tags `[fact: step N]`, `[assumption]`, `[scenario]` |
| `server/explainer.py` | Builds the evidence panel from the trace (no LLM): sector cards, risk charts vs limits, profile check, sources |
| `apps/web/` | React + Vite app: persona picker, custom profile, chat, Simple/Detailed views, EN/FR |

## 4. Data

| Data | Source |
|---|---|
| Daily prices, dividends, splits (31 assets, 2021-11-12 → 2026-11-12) | Organizers' starter dataset (Yahoo Finance via `yfinance`) |
| USD/CAD, Canadian rates and CPI | Bank of Canada Valet API |
| U.S. rates, CPI, unemployment, yield curve, Sahm rule, recession probability, industrial production, VIX, high-yield spread, consumer sentiment | FRED (Federal Reserve Bank of St. Louis) |

Every file's source, URL, retrieval date, processing and terms are in `data/sources_metadata.csv`.

**Processing choices**

- Returns use `adj_close`, converted to CAD with the last Bank of Canada USD/CAD rate on or before each date
  (`merge_asof`, backward). USD assets also report volatility in USD to show the currency effect.
- Annualization: 252 trading days (365 for crypto).
- **Sector groups** (13): 9 industries are equal-weight baskets rebalanced daily on common dates. Building blocks
  (Bonds, Broad market, Gold, Crypto) are reported per member with a min–max range, never blended, because
  near-cash and long-Treasury funds are too different to average.
- **No look-ahead:** no fund-size weights (today's snapshot would leak the future), monthly macro is treated as
  published 21 days after its month (35 days for the recession probability), and tests check that no result uses
  data after the analysis date.
- **Risk label:** volatility < 10% Low · 10–20% Moderate · 20–35% High · > 35% Very High; a max drawdown worse than
  −30% bumps the label up one level.
- **2022 stress test:** last 2021 close to last 2022 close, the only recent year where stocks and bonds fell
  together.

## 5. Explainability and trust

| Mechanism | What it guarantees |
|---|---|
| Workers in Python, unit-tested | Every number is computed by code, not generated by a model |
| Answer check (`reviewer.check_answer`) | Every number in the answer must appear in the worker step it cites; otherwise the presenter rewrites once, then a visible reviewer note is added |
| Work review | Requested and recommended targets must have a real risk analysis, a suitability check and (for recommendations) momentum; no recommended group may have a conflict |
| Claim tags | Each sentence is tagged `fact` (with its step), `assumption` or `scenario`; the UI turns them into chips that open the trace |
| Evidence panel | Built from the trace without an LLM, so it cannot hallucinate |
| Run trace in S3 | Who did what, with which data, how long it took and what the reviewer decided |
| Bedrock Guardrail | Blocks personal advice to the real user, trades, PII and prompt attacks, on input and output |
| Sanity check script | `scripts/sanity_check.py` recomputes 31 numbers independently |

Persona fit is deliberately **not** handled by the guardrail: the suitability worker evaluates it, so the bot can
explain a conflict ("NVDA's 51.1% volatility vs Robert's 10.0% limit") instead of refusing.

## 6. Evaluation

We built an evaluation harness (`scripts/eval/`) that runs the **real Bedrock pipeline** with the guardrail on, and
uses **Claude Opus 5.5 as an independent judge** of each answer. Full results:
[eval_report.md](eval_report.md); raw files in `reports/eval/` and `s3://$DATA_BUCKET/runs/eval/`.

**Baseline run: 600 questions, 6 profiles (3 personas + 3 questionnaire profiles), about 20% in French**

| Metric | Result |
|---|---|
| Work review passed | 100% |
| Answer check passed (final / first draft) | 99.7% / 95.7% |
| Recommends a group with a suitability conflict | 0% |
| Normal questions wrongly blocked by the guardrail | 0% |
| Latency p50 / p95 | 17.1 s / 22.9 s |
| First text p50 | 4.7 s |
| Estimated cost per answer | $0.073 |
| Judge scores (1–5): faithfulness / suitability / clarity | 3.83 / 3.84 / 3.92 |

**Red team: 200 adversarial prompts** (guaranteed returns, ignore the limits, other users' data, personal advice,
prompt injection): **57% blocked by the guardrail, 43% refused by the app, 0% answered.** All 40 prompt injections
were blocked. The 3 flagged "rule breaks" were false alarms: the judge confirmed the bot refused in each case.

**Model choice for the presenter** (same questions, judged by Opus 5.5): Opus 5.5 writes the best answers but takes
about 3–4× longer to the first text and costs about twice as much; Sonnet 4.6 stays the default for a responsive
chat. Results: `reports/eval/baseline/compare_presenters.csv`.

### 6.1 What the evaluation found, and what we fixed

<!-- TEAM: keep this subsection only if the presenter-facts PR is merged. -->

The judge's lowest scores came from three presenter mistakes that the number check could not catch, because both
numbers were real:

1. **Wrong comparisons**, e.g. calling Consumer Staples' 17.0% volatility "lower" than Financials' 15.7%.
2. **Relabelled statuses**, e.g. calling a `pass` an `info`.
3. **Claims not in the trace**, e.g. "survivorship bias", which the old presenter prompt itself used as an example.

Fix (`comparisons.py`, presenter prompt, reviewer):

- Python now computes every ranking and comparison and gives the presenter ready-made sentences
  ("Utilities has the lowest volatility (14.7%), Financials 2nd (15.7%)…"), recorded as a `compare_metrics` trace
  step. The presenter may not compare numbers itself.
- The reviewer rejects a comparative word (lower, higher, safer, best…; French included) next to two numbers in the
  wrong order, and any status word that differs from the trace.
- On the 40 earlier judged answers, the new checks flag exactly the 4 the judge criticised for these reasons, and
  nothing else.

## 7. Testing

- Unit, pipeline, contract and server tests (`python -m pytest -q`), all passing; live Bedrock tests run only with
  `RUN_LIVE=1`.
- Tests cover look-ahead, the risk labels, suitability rules, ranking, the answer check (including wrong
  comparisons and statuses), guardrail handling and the API contract.
- `scripts/benchmark.py` for latency, `scripts/eval/` for quality, safety and cost (section 6).

## 8. Performance and cost

- A full answer went from 44–65 s to 13–17 s by giving the boss coarse tools with compact results (the full output
  stays in the trace), running tool calls in parallel, using Haiku 4.5 for planning and streaming the presenter.
- The answer opens with a summary of at most 3 bullets, so the user reads the verdict in about 5 s.
- About **$0.07 per answer** on Bedrock on-demand prices.

## 9. Limitations

- **Small universe:** 31 assets from the organizers; five sector groups contain a single asset (labelled
  "1 asset, not diversified").
- **Survivorship bias:** the universe was chosen in 2026. FRED values are revised vintages.
- **No ESG, news or fundamentals data yet:** Mateo's ESG-review flags have no evidence until the ethics worker is
  built (design in `guardrails/03_workers_ethics.md`).
- **The answer check verifies numbers and citations, not units or meaning;** the judge evaluation and the trace
  cover the rest.
- **The guardrail fails open** if its API errors; the trace records it and persona rules still apply.
- **Prototype server:** one run at a time per process, conversations in memory, sign-in not configured, so it must
  not be exposed publicly as is.
- **Persona limits are team assumptions**, not part of the brief.

## 10. Next steps

- Ethics and news workers with sourced evidence (Amazon Bedrock AgentCore web search).
- Larger universe (full sector indices) and point-in-time macro data.
- Managed deployment with sign-in (Amazon Cognito) and persistent conversations.
- Run the evaluation on every change, to keep the judge scores and red-team results as regression tests.
