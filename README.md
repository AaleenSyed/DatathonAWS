# AlphaForge AI: PolyFinances Datathon 2026

A self-explaining, agentic decision-support chatbot. You pick a fictional investor persona (Amira, Mateo or
Robert) and ask a question in plain language, in English or Canadian French. The system recommends a sector
group that fits that persona, checks the request against the persona's limits, and shows every number with its
source, period and currency. When a request does not fit the profile, it says so and explains why with numbers.

> **Educational simulation for fictional personas. Not personalized financial advice. No real transactions.**

Example: Robert (59, near retirement) asks *"Can I put a big part of my savings in NVDA?"* The answer opens with
a summary: NVDA conflicts with his profile (a 50.0% position vs his 10.0% single-stock cap, 51.1% volatility vs
his 10.0% limit). It recommends Consumer Staples paired with Bonds, and every claim links to the trace step that
produced it.

## Status

| Phase | State |
|---|---|
| 1. Foundations: personas, data retriever, risk analyst | Done |
| 2. Suitability and market context workers | Done |
| 3. Chat pipeline: boss, reviewer, presenter, run trace, terminal chat | Done |
| 3b. Intent router: conversational replies (greetings, questions about the assistant, concept explanations, off-topic) before the pipeline | Done |
| 4. Bedrock Guardrail on the question and the answer, PII redaction in traces | Done (needs a guardrail ID in `.env`) |
| 5. News sentiment and ethics workers | Not built; designs in `guardrails/03_workers_news_sentiment.md` and `03_workers_ethics.md` |
| 6. Web app: FastAPI backend + React frontend, EN/FR | Done |
| 7. Docs: this README, technical doc, one-pager, video | In progress |

Tests: 535 pass (13 live Bedrock tests run only with `RUN_LIVE=1`).

## How it works

```
User question (persona fixed by the session)
  → Bedrock Guardrail (input)
  → INTENT ROUTER: rules (ticker, sector, investing keyword, short follow-up), then one Claude Haiku 4.5 call;
      conversation (smalltalk, about, explain, off_topic) → short reply checked in code and by the output guardrail → done
      investing question or follow-up ↓
  → BOSS: Claude Haiku 4.5 on Bedrock, a Strands agent; calls every tool it needs in one parallel turn, then returns a plan
  → WORKERS: deterministic Python, no LLM; risk, 2022 stress test, suitability, sector ranking, market context
  → REVIEWER: deterministic checks of the work; on failure the boss gets the reasons (max 2 retries)
  → COMPARISONS: ranks and comparison sentences computed in Python (comparisons.py), reused by the presenter
  → PRESENTER: Claude Sonnet 4.6 on Bedrock, streamed; writes the answer from the worker results only
  → REVIEWER: every number in the answer must appear in the cited worker step (max 1 rewrite)
  → Bedrock Guardrail (output) → answer + structured explanation + full run trace (local and S3)
```

- **Analysis only when it is needed.** `router.py` answers conversation directly: "hi", "what can you help me
  with?", "what does volatility mean?" or "what color is the sky?" get a short reply in about 1.5 s instead of a
  report. Obvious investing questions skip the model call; when unsure, the router chooses the analysis. An
  explanation ends with an offer, and "yes" runs the analysis on the earlier question. Live test: 29/29 EN/FR
  messages routed correctly, no investing question answered as chat (`tests/test_live_router.py`).
- **The LLMs never compute numbers.** All the math is in `workers/`, which is plain Python with unit tests. The
  boss chooses which tools to call and what to recommend; the presenter turns the results into prose.
- **Recommendations are consistent.** `rank_sectors_for_persona` ranks every industry by the persona's rules:
  overall pass first, then the fewest cautions, then the smallest breach of the volatility and 2022-drawdown
  limits. A group with a conflict is never recommended. When the persona needs another asset class or a bonds
  minimum, the industry is paired with a building block (Bonds).
- **Explainability.** The answer tags each claim `[fact: step N]`, `[assumption]` or `[scenario]`. The web app
  shows these tags as chips that open the trace at that step. Under each answer, `server/explainer.py` builds a
  structured panel from the trace (no LLM): sector cards, risk charts against the persona's limits, the profile
  check rule by rule, market context, claims with sources, the reviewer's verdicts and the limitations.
- **Speed.** A full answer takes 13–17 s on Bedrock and the first text appears after 4–6 s, down from 44–65 s.
  Details: `reports/benchmark.md`.

## AWS integration

| Service | Use |
|---|---|
| Amazon Bedrock, Converse API (via Strands) | Claude Haiku 4.5 (`global.` inference profile): the intent router (classification and conversational reply, structured output) and the boss agent |
| Amazon Bedrock, ConverseStream | Presenter, Claude Sonnet 4.6; the text is streamed to the browser |
| Amazon Bedrock Guardrails, ApplyGuardrail | Filters the question, the final answer and every conversational reply: denied topics (personal advice to the real user, real trades), PII, content and prompt-attack filters |
| Amazon S3 | Run traces (`s3://$DATA_BUCKET/runs/<run_id>.json`, linked in the UI); data files can be read from `s3://$DATA_BUCKET/data/` |
| Amazon Cognito | ID-token verification implemented and tested in `server/auth.py`; no user pool configured yet, so the server runs in dev mode |

Region: `us-east-1`. No other model provider is called. Credentials come from the environment, never from the repo.

## Run it

**Requirements:** Python 3.11+, Node 20+ with pnpm, AWS credentials with Bedrock access (not needed in demo
mode), and the data files in `data/`.

The CSVs are not in git (see "Data"). Put the starter dataset in `data/`, then run `python data/fetch_fred_extra.py`
for `data/macro_extra.csv`, or set `DATA_SOURCE=s3` and `DATA_BUCKET` to read them from S3.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q                                   # 535 tests

# Backend (terminal 1)
uvicorn server.app:app --port 8000                    # real agent on Bedrock
AGENT_MODE=demo uvicorn server.app:app --port 8000    # scripted boss/presenter, real worker numbers, no Bedrock cost

# Web app (terminal 2)
pnpm install
pnpm web:dev                                          # http://localhost:5173 ; /api is proxied to :8000
```

Other entry points:
- `python chat.py`: terminal chat (`/trace`, `/persona`, `/quit`).
- `RUN_LIVE=1 python -m pytest -q -s tests/test_live_demo.py tests/test_live_server.py`: the demo questions end to
  end on Bedrock (costs a few cents).
- `python scripts/benchmark.py --warm`: latency benchmark on Bedrock.

Settings (`.env`, never committed):

| Variable | Meaning |
|---|---|
| `DATA_BUCKET` | S3 bucket for run traces (and data with `DATA_SOURCE=s3`) |
| `GUARDRAIL_ID`, `GUARDRAIL_VERSION` | Bedrock Guardrail; unset = off (also off in demo mode). Version defaults to `DRAFT` |
| `AGENT_MODE` | `bedrock` (default) or `demo` |
| `BOSS_MODEL`, `PRESENTER_MODEL` | Override the default models |
| `ROUTER_MODEL`, `ROUTER_LLM` | Intent router model (default Haiku 4.5); `ROUTER_LLM=0` turns its LLM step off (rules only) |
| `TOOL_CACHE`, `WARM_UP` | `0` disables the per-process worker cache / the start-up warm-up |
| `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID` | Set both to require Cognito sign-in tokens |

## Evaluation

`scripts/eval/` runs the real Bedrock pipeline (guardrail on) and uses Claude Opus 5.5 as an independent judge.
Full results: [`docs/eval_report.md`](docs/eval_report.md); raw files in `reports/eval/baseline/` and
`s3://$DATA_BUCKET/runs/eval/baseline/`.

| Baseline (600 questions, 6 profiles, ~20% French) | Result |
|---|---|
| Answer check passed (final / first draft) | 99.7% / 95.7% |
| Recommends a group with a suitability conflict | 0% |
| Normal questions wrongly blocked by the guardrail | 0% |
| Latency p50 / first text p50 | 17.1 s / 4.7 s |
| Estimated cost per answer | $0.073 |
| Judge (1–5): faithfulness / suitability / clarity | 3.83 / 3.84 / 3.92 |
| Red team (200 adversarial prompts) | 57% blocked by the guardrail, 43% refused, 0% answered |

The judge's low scores came from wrong comparisons and relabelled statuses in the presenter's text; comparisons
are now computed in Python (`comparisons.py`) and checked by the reviewer (see `docs/technical.md`, section 6.1).

Run it: `bash scripts/eval/run_all.sh <label> <concurrency> <budget_usd>` (resumes if interrupted).

## Web app

React + Vite in `apps/web/`, talking to the FastAPI backend in `server/` over the contract in `contracts/`
(OpenAPI for REST, AsyncAPI for the WebSocket). The details are in `apps/web/README.md`.

- **Persona picker:** an animated character for each built-in persona (Amira, Mateo, Robert), with the goal, risk
  and horizon; or build your own fictional profile with 7 questions. The limits are not shown on the cards, but
  every request is still checked against them.
- **Chat:** one-click demo questions; live progress (planning, analysing, reviewing, writing); the answer streams in.
  The persona's character animates while it "talks". Follow-up suggestions appear above the message bar, one at a
  time.
- **Conversation:** greetings, questions about the assistant, concept explanations and off-topic messages get a
  short reply from the intent router, without an evidence panel.
- **Summary first:** every answer starts with a summary of at most 3 bullets, coloured by the profile check (green
  = fits, amber = caution, red = conflict). The full analysis and the evidence open on demand. A Simple /
  Detailed switch sets the default for every answer.
- **Profile check:** a verdict badge at the top of each analysis ("Fits Robert's profile", "Flagged: above some of
  Robert's limits", "Conflicts with Robert's profile") with the rules that did not pass, the sectors that fit
  better, and a clear notice when the Bedrock Guardrail blocked the request or the answer.
- **Stock cards:** every stock in the answer as a card with a volatility ring (under 15%, 15 to 30%, over 30%),
  taken from the risk analyst's output in the trace, in CAD; a card opens its trace step. Stock and sector names
  are bolded in the summary.
- **Evidence:** sector cards, risk charts with the persona's limit, the profile check, market context, claims
  with short source labels, the reviewer's verdicts, worker warnings and the full trace with input/output JSON.
- **Other features:**
  - English and Canadian French, switchable at any time; the next answer is written in the new language.
  - Original "noir" theme (dark by default, with an animated starfield; light available), WCAG AA contrast
    checked by `apps/web/scripts/contrast.mjs`. Animations stop with "reduce motion".
  - A- / A+ buttons scale the answer text from 60% to 150%, remembered per browser.
  - Works down to 320 px wide with no horizontal scroll.
  - Edit and regenerate, with version arrows.
  - Reconnects without losing an answer in progress.

## Repository

| Path | Role |
|---|---|
| `personas.py` | Fictional personas and their limits (team assumptions) |
| `workers/data_retriever.py` | Prices (adj_close, USD→CAD), FX, macro (publication-lag aware), asset info |
| `workers/risk_analyst.py` | Asset/sector return, volatility, drawdown, correlation, 2022 stress test, risk labels |
| `workers/market_context.py` | Business-cycle phase (FRED rules), fear vs hope, sector momentum / trend / relative strength |
| `workers/suitability.py` | Checks a ticker or sector against a persona's limits: pass / info / flag / conflict per rule |
| `agent_tools.py` | Workers as Strands `@tool`s: coarse `assess_target`, `rank_sectors_for_persona`, `market_snapshot` and the fine tools. The boss gets compact results; the trace keeps the full output. Persona and dates are fixed by the session |
| `router.py` | Intent router: rules first, then one Haiku call (intent, confidence, reply); replies with a digit, `%` or universe asset are rejected and replaced by fixed EN/FR texts (`texts.py`), also used in demo mode |
| `pipeline.py` | `ChatSession`: guardrail → router (short reply, or →) boss → reviewer (max 2 retries) → comparisons → presenter → answer check (max 1 retry) → guardrail → trace |
| `reviewer.py` | Deterministic checks: work coverage, sources, periods, persona limits, ESG check, no look-ahead; every answer number must be in the cited worker step; no promised returns |
| `presenter.py` | Streamed answer with claim tags, from the plan-relevant trace steps |
| `guardrail.py` | Bedrock ApplyGuardrail on input and output; PII redaction before anything is written to the trace |
| `run_trace.py` | Run trace with per-step durations and LLM-call timing, saved to `runs/` and S3 |
| `server/` | FastAPI REST + WebSocket backend, explainer, demo agent, auth |
| `apps/web/`, `packages/api-client/` | React app and its typed client, generated from `contracts/` |
| `prompts/` | Router, boss and presenter system prompts, language rules |
| `AGENT_GUARDRAILS.md`, `guardrails/` | Rules for every agent (summary, then one file per agent) |
| `scripts/` | `benchmark.py`, `sanity_check.py` (31 independent number checks), `inspect_target.py` |
| `tests/` | Unit, pipeline, contract and server tests; live Bedrock tests behind `RUN_LIVE=1` |

## Data

The 5-year window runs from 2021-11-12 to 2026-11-12, so the 2022 stocks-and-bonds drawdown is in the sample.
The analysis date is 2026-11-12. The source, URL, retrieval date, processing, limitations and terms of every file
are listed in `data/sources_metadata.csv`.

| Data | Source | Terms |
|---|---|---|
| Daily prices, dividends, splits | Yahoo Finance via the open-source `yfinance` library (starter dataset) | [Yahoo terms](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html) |
| USD/CAD, Canadian policy rate, 2y/10y yields, CPI | Bank of Canada Valet API | [Bank of Canada terms](https://www.bankofcanada.ca/terms/) |
| U.S. fed funds, 2y/10y yields, CPI, unemployment | FRED, Federal Reserve Bank of St. Louis | [FRED terms](https://fred.stlouisfed.org/legal/) |
| Yield curve (T10Y2Y), Sahm rule (SAHMREALTIME), recession probability (RECPROUSM156N), industrial production (INDPRO), VIX (VIXCLS), high-yield spread (BAMLH0A0HYM2), consumer sentiment (UMCSENT) | FRED, fetched by `data/fetch_fred_extra.py` into `data/macro_extra.csv` | FRED terms; some series carry third-party copyright (ICE BofA, University of Michigan, Cboe) |
| Asset universe and sector labels | Datathon organizers | Datathon use |

The CSVs are not committed (team rule; `data/*.csv` is in `.gitignore`, except `sources_metadata.csv`).

**Universe:** 31 assets.
- 20 companies: 10 Canadian on the TSX, 10 U.S. on NASDAQ and NYSE.
- 9 ETFs: broad market, bonds, gold and one ESG-screened fund.
- 2 cryptocurrencies: Bitcoin and Ether.

They form 13 sector groups:
- 9 industries, made of stocks only: Financials, Energy, Information Technology, Consumer Staples, Consumer
  Discretionary, Industrials, Utilities, Communication Services, Health Care.
- 4 building blocks: Bonds, Broad market, Gold, Crypto asset.

## Team assumptions
- **Persona limits** (`personas.py`) are team assumptions, not part of the brief:
  - Amira: crypto ≤ 15%, single stock ≤ 15%, tech ≤ 50%, at least 3 asset classes.
  - Mateo: no crypto, volatility ≤ 15%, bonds ≥ 30%, ESG review of ENB, CNQ, XOM.
  - Robert: no crypto, single stock ≤ 10%, volatility ≤ 10%, bonds/cash ≥ 50%, 2022 drawdown no worse than −15%.
- **Returns** come from `adj_close`, in CAD. USD is converted with the Bank of Canada USD/CAD rate, using the last
  available rate on or before each date. Annualized with 252 days; 365 for crypto.
- **Risk label**: annualized volatility < 10% Low · 10–20% Moderate · 20–35% High · > 35% Very High. A max drawdown
  worse than −30% bumps the label up one level.
- **Groups** come from the organizers' `sector` labels (the exact label, or the text before " (", e.g. "Bonds").
  - **Industries** (all members `equity`): equal-weight basket, rebalanced daily, on common dates.
  - **Building blocks** (ETFs and crypto: Bonds, Broad market, Gold, Crypto asset): each member is reported
    separately with the min–max range, with no blended figure. For example, near-cash ZST.TO and long-Treasury
    TLT are too different to average.
- **USD assets** also report volatility in USD, to show how much of the CAD risk comes from the exchange rate.
- **2022 stress test**: last 2021 close (2021-12-31) to last 2022 close.
- **Monthly macro** counts as published 21 days after the end of its reference month, and RECPROUSM156N after 35
  days. Its Sep 2026 value was "Updated: Nov 2, 2026" on the FRED series page, retrieved 2026-11-14.
- **Business-cycle phase**: a historical tendency, labelled `assumption`, never a prediction. The rules are
  checked in this order:
  1. Recession risk: SAHMREALTIME ≥ 0.5 or RECPROUSM156N ≥ 30.
  2. Early cycle: a recession signal in the past 12 months, and INDPRO above its value 3 months earlier.
  3. Late cycle: T10Y2Y < 0 now or in the past 12 months.
  4. Mid cycle otherwise.

  The sector tilts per phase are listed in `CLAUDE.md`.
- **Fear vs hope**: VIX < 15 calm/hope, 15–25 normal, > 25 fear. A high-yield spread higher than 3 months earlier
  counts as credit stress.
- **Momentum/trend**: 6- and 12-month return, 12-month relative strength vs XIU.TO (`.TO` tickers) or SPY (others),
  price vs its 200-observation average, and drawdown from the 12-month high. Industry baskets are compared with an
  equal-weight mix of their members' benchmarks.
- **Suitability statuses**:
  - `conflict`: excluded asset type, or a proposed weight above a cap.
  - `flag` (shown as "Caution"): volatility or 2022 drawdown on its own above a portfolio limit, or an ESG review.
  - `info`: a portfolio-level reminder, such as a bonds minimum, or a cap to respect when no weight is proposed
    ("keep at most 15.0%").
  - `pass`, `not_applicable`, `not_evaluated`.

  Rules:
  - Caps (crypto, single stock, sector) only give `conflict` or `pass` once a weight is proposed; without one
    they are `info`.
  - Volatility above a portfolio limit is a `flag`, not a `conflict`, because a small slice can still fit a
    lower-risk portfolio.
  - A proposed weight that leaves less than the bonds minimum for the rest of the portfolio is a `conflict`.
  - A one-asset industry (e.g. Utilities = FTS.TO) counts as a single stock.

  Overall verdict: `conflict` > `flag` > `incomplete` (something not evaluated) > `pass`.
- **Ranking**: pass > fewest cautions > smallest volatility / 2022-drawdown breach; conflicts are excluded.
  Tie-breakers, in order: diversified groups before one-asset groups, the current cycle tilt, lower volatility.
- **Pipeline**: when the user implies "a big part" without a number, the boss assumes a 50% share and says so.
  Plain words map to targets with a small alias list (crypto, bitcoin, tech, bonds, gold...) in `reviewer.py`.
- **Answer check**: every number must match a worker result, as written or ×100, within its rounding.
  - In a sentence tagged `[fact: step N]`, the number must come from the cited step(s), and citations must point
    to worker steps.
  - Bare counts 0–12 ("3 asset classes") are exempt; percentages and decimals are not.
  - After one rewrite, a visible reviewer note is added to the answer.
- **Work review**:
  - Requested and recommended targets need a real risk analysis (not just a stress test) and a suitability check.
  - Recommended sectors also need momentum, and must not have a suitability `conflict`.
  - Every ESG-review name must be checked.
  - A worker error must be retried successfully or explained in the boss's notes.

## Limitations
- **Small universe.** The 31 assets are the organizers' starter set. Five sector groups contain one asset each
  (Communication Services, Health Care, Industrials, Utilities, Gold); the app labels them "1 asset, not
  diversified", and the ranking prefers diversified groups when its other rules tie. A production version would
  use a full sector index.
- **Survivorship bias:** the universe was picked in 2026.
- **Revised data:** FRED values are revised vintages, not what was known at the time.
- **CNQ.TO:** the 1.021 "split" on 2022-08-22 is likely a special distribution.
- **No ESG, news or fundamentals data.** Mateo's ESG-review flags have no evidence until the ethics worker is built.
- **Credit-stress signal:** FRED only serves the last 3 years of the high-yield spread (from 2023-11-14), so there
  is no credit-stress signal before that date.
- **What the answer check covers.** It verifies numbers and citations, not units, signs or wording:
  - a correct number with the wrong unit, sign or meaning can pass;
  - a whole-number percent can match an unrelated value in the cited step by chance.

  Every answer has a full trace for auditing.
- **The guardrail fails open.** If the Bedrock Guardrail API errors, the answer still goes through and the trace
  records it. Persona-fit rules stay in the suitability worker either way.
- **Conversational replies.** Replies to greetings, questions about the assistant and general concept explanations
  are written by Claude Haiku 4.5 without data; code rejects any such reply containing a digit, a % sign or an asset
  from the universe. Only analysis answers carry figures, each with source and period. Numbers spelled out in words
  pass the code check (only the prompt and the guardrail cover them), and French replies sometimes use "tu" instead
  of "vous". In demo mode, a message with no investing signal gets a fixed "not sure I can help" reply.
- **Literal word matching.** Target words are matched literally: "I have little energy..." makes the reviewer
  require an Energy analysis. This costs extra tool calls, not a wrong answer.
- **Member metrics:** inside a sector, they use the sector's common dates, so a member's volatility can differ
  slightly from its standalone value (NVDA 51.4% vs 51.1%).
- **Server limits:**
  - One analysis at a time per server process (`agent_tools.CONTEXT` is process-wide); other analyses wait as
    "queued". The router and conversational replies run outside that lock, so a greeting never waits.
  - Conversations live in memory and are lost on restart (traces stay in `runs/` and S3).
  - Sign-in is not wired, so the server must not be exposed publicly in dev mode.
