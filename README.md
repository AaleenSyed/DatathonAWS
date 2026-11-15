# AlphaForge AI: PolyFinances Datathon 2026

Self-explaining agentic decision-support chatbot. Pick a fictional investor persona (Amira, Mateo, Robert),
ask a question, and the system recommends a sector that fits the persona, with risk numbers, sources,
assumptions and limitations.

> **Educational simulation for fictional personas. Not personalized financial advice. No real transactions.**

## Status
- [x] Phase 1: personas, data_retriever, risk_analyst, tests
- [x] Phase 2: suitability + market context
- [x] Phase 3: chat pipeline (boss, reviewer, presenter, trace)
- [ ] Phase 4: Bedrock Guardrail
- [ ] Phase 5: news + ethics workers
- [ ] Phase 6: Streamlit UI
- [ ] Phase 7: docs

## Setup
```
py -3.14 -m venv .venv            # Python 3.11+
.venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q
python chat.py                     # terminal chatbot (needs AWS credentials for Bedrock)
```
Live demo questions on Bedrock (costs a few cents): `RUN_LIVE=1 python -m pytest -q -s tests/test_live_demo.py`
Data CSVs go in `data/` (gitignored) or are read from `s3://$DATA_BUCKET/data/` (set `DATA_BUCKET` in `.env`).
AWS credentials come from the environment / `~/.aws/credentials`, never from the repo.

## Architecture
See `CLAUDE.md` (pipeline) and `AGENT_GUARDRAILS.md` (guardrails per agent). Agent definitions: `agents/`.

| File | Role |
|---|---|
| `personas.py` | Fictional personas and their limits |
| `workers/data_retriever.py` | Prices (adj_close, USD→CAD), FX, macro (publication-lag aware), asset info |
| `workers/risk_analyst.py` | Asset/sector return, vol, drawdown, correlation, 2022 stress test, risk labels |
| `workers/market_context.py` | Business-cycle phase (FRED rules), fear vs hope, sector momentum/trend/relative strength |
| `workers/suitability.py` | Checks a ticker or sector against a persona's limits: pass/info/flag/conflict per rule |
| `pipeline.py` | ChatSession: boss (Strands agent, Sonnet 5 on Bedrock) → worker tools → reviewer (max 2 retries) → presenter → answer check → trace |
| `agent_tools.py` | Workers wrapped as Strands `@tool`; persona and dates fixed by the session; every call logged to the trace |
| `reviewer.py` | Deterministic checks: work coverage, sources, periods, persona limits, ESG check, no look-ahead; every answer number must be in the worker results |
| `presenter.py` | Final answer with Sonnet 5 (Bedrock Converse), claims tagged `[fact: step N]` / `[assumption]` / `[scenario]` |
| `run_trace.py` | Run trace saved to `runs/` and `s3://$DATA_BUCKET/runs/` |
| `chat.py` | Terminal chat: pick a persona, multi-turn Q&A, `/trace` shows the steps |
| `prompts/` | Boss and presenter system prompts |
| `data/fetch_fred_extra.py` | One-off fetch of extra FRED series → `data/macro_extra.csv` |

## Data sources
Full list with URLs, retrieval dates, processing, terms and limitations: `data/sources_metadata.csv`.
- Prices, corporate actions: Yahoo Finance via yfinance (Yahoo terms of use)
- USD/CAD FX, Canadian yields, policy rate, CPI: Bank of Canada Valet API
- U.S. rates, CPI, unemployment: FRED (Federal Reserve Bank of St. Louis)
- Yield curve (T10Y2Y), Sahm rule (SAHMREALTIME), recession probability (RECPROUSM156N), industrial production
  (INDPRO), VIX (VIXCLS), high-yield spread (BAMLH0A0HYM2), consumer sentiment (UMCSENT): FRED, via
  `data/fetch_fred_extra.py` (labels and units read from each FRED series page)
- Universe and sector labels: datathon organizers

## Team assumptions
- **Persona limits** (`personas.py`) are team assumptions, not part of the brief.
- **Returns** from `adj_close`, in CAD (USD converted with Bank of Canada USD/CAD, last available rate on or
  before each date). Annualized with 252 days; 365 for crypto.
- **Risk label**: annualized vol < 10% Low · 10–20% Moderate · 20–35% High · > 35% Very High; max drawdown worse
  than −30% bumps the label up one level.
- **Groups** come from the organizers' `sector` labels (exact label, or the text before " (", e.g. "Bonds").
  - **Industries** (all members `equity`): equal-weight basket, rebalanced daily, on common dates.
  - **Building blocks** (ETFs and crypto: Bonds, Broad market, Gold, Crypto asset): each member reported
    separately with the min–max range; no blended figure (e.g. near-cash ZST.TO vs long-Treasury TLT).
- **USD assets** also report volatility in USD, to show how much of the CAD risk comes from the exchange rate.
- **2022 stress test**: last 2021 close (2021-12-31) to last 2022 close.
- **Monthly macro** counts as published 21 days after the end of its reference month; RECPROUSM156N 35 days
  (its Sep 2026 value was "Updated: Nov 2, 2026" on the FRED series page, retrieved 2026-11-14).
- **Business-cycle phase** (historical tendency, labelled `assumption`, never a prediction), checked in order:
  Recession risk (SAHMREALTIME ≥ 0.5 or RECPROUSM156N ≥ 30) → Early cycle (recession signal in the past 12 months
  and INDPRO above its value 3 months earlier) → Late cycle (T10Y2Y < 0 now or in the past 12 months) → Mid cycle.
  Sector tilts per phase as in `CLAUDE.md`.
- **Fear vs hope**: VIX < 15 calm/hope, 15–25 normal, > 25 fear; high-yield spread higher than 3 months earlier =
  credit stress.
- **Momentum/trend**: 6- and 12-month return, 12-month relative strength vs XIU.TO (`.TO` tickers) or SPY (others),
  price vs 200-observation average, drawdown from the 12-month high. Industry baskets are compared with an
  equal-weight mix of their members' benchmarks.
- **Suitability statuses**: `conflict` (excluded asset type or proposed weight above a cap), `flag` (standalone
  vol / 2022 drawdown above a portfolio limit, or ESG review), `info` (portfolio-level reminder: a bonds
  minimum, or a cap to respect when no weight is proposed, e.g. "keep at most 15.0%"), `pass`, `not_applicable`,
  `not_evaluated`. Caps (crypto, single stock, sector) only give `conflict` or `pass` once a weight is proposed;
  without one they are `info`, never `flag`. Standalone vol above a portfolio limit is a `flag`, not a
  `conflict`: a small slice can still fit a lower-risk portfolio. A proposed weight that leaves less than the
  bonds minimum for the rest is a `conflict`. A one-asset industry (e.g. Utilities = FTS.TO) counts as a single
  stock. The 2022 stress check is `not_evaluated` when the analysis ends before 2022-12-31. Overall verdict:
  `conflict` > `flag` > `incomplete` (something not evaluated) > `pass`.

- **Pipeline**: the boss assumes a 50% share when the user implies "a big part" without a number (stated in the
  answer). Plain words map to targets with a small alias list (crypto, bitcoin, tech, bonds, gold...) in `reviewer.py`.
- **Answer check**: every number must match a worker result (as written or ×100, within its rounding). On a line
  tagged `[fact: step N]` it must come from the cited step(s); citations must point to worker steps. Bare counts
  0–12 ("3 asset classes") are exempt, but not percentages or decimals. Max 2 rewrites, then a visible reviewer note.
- **Work review**: requested and recommended targets need a real risk analysis (not just a stress test) and a
  suitability check; recommended sectors also need momentum and must not have a suitability `conflict`; every
  ESG-review name must be checked; a worker error must be retried successfully or explained in the boss notes.

## Limitations
- Survivorship bias: the universe was picked in 2026.
- FRED values are revised vintages, not what was known at the time.
- CNQ.TO 1.021 "split" on 2022-08-22 is likely a special distribution.
- The answer check verifies numbers and citations, not units, signs or wording: a right number with a wrong unit,
  sign or meaning can pass, and a whole-number percent can match some unrelated value in the cited step by chance.
  Every answer has a full trace to audit it.
- Target words are matched literally: "I have little energy..." makes the reviewer require an Energy analysis
  (extra tool calls, not a wrong answer).
- Inside a sector, member metrics use the sector's common dates, so a member's volatility can differ slightly from
  its standalone `analyze_asset` value (e.g. NVDA 51.4% vs 51.1%).
- One active chat session per process: `agent_tools.CONTEXT` (persona, analysis date, current trace) is a module
  global. A UI serving several users in one process must run sessions one at a time or move this to per-session state.
- Until the Bedrock Guardrail (phase 4), the user's question is stored as typed in `runs/` and `s3://…/runs/`.
- Several sectors have only one asset (Communication Services, Health Care, Industrials, Utilities, Gold).
- No ESG, news or fundamentals data in the starter set; ESG-review flags for Mateo have no evidence until the
  ethics worker (phase 5).
- FRED only serves the last 3 years of the high-yield spread (from 2023-11-14): no credit-stress signal before
  that date.
