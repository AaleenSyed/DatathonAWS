# AlphaForge AI: PolyFinances Datathon 2026 prototype

Self-explaining agentic decision-support tool. A user picks a fictional investor persona
(Amira, Mateo, Robert), makes a request or asks a question, and the system analyzes public
financial data, checks the request against the persona's constraints, and explains its
conclusion with sources, assumptions, and limitations.

Simulation only. No real transactions. Never presented as personalized financial advice.

## Deadlines
- Repo + README due Sunday Nov 15, 23:59. AWS account is deleted Monday Nov 16, 13:59.
- Deliverables: prototype, repo/README, ~5 min video, technical doc, one-pager.

## Judging grid (optimize for this)
Solution quality/innovation 20% · Agentic + explainability 20% · Data rigour/validation/viz 20% ·
UX/UI 10% · AWS integration 15% (ELIGIBILITY REQUIREMENT: AWS must play a real, demonstrable role) ·
Pitch/business value 15%. Complexity and number of agents are NOT rewarded for their own sake.

## Personas (from the official brief; numeric limits are our team's assumptions, document them)
- **Amira**, 26, software engineer. Risk HIGH, horizon 15+ yrs. Long-term growth; likes AI,
  emerging tech, crypto; still wants diversification, not 100% tech.
  Test: "high risk" ≠ "anything goes". Assumed limits: crypto ≤ 15%, single stock ≤ 15%,
  tech sector ≤ 50%, at least 3 asset classes.
- **Mateo**, 41, operations manager, partner + 2 kids. Risk MODERATE, horizon 8–12 yrs.
  Balanced growth; strong ESG preference; avoid companies with significant environmental/social
  controversies; little interest in speculative assets.
  Test: use non-financial criteria, not just return/risk. Assumed limits: crypto 0%,
  annualized vol ≤ 15%, bonds ≥ 30%, flag energy names (ENB, CNQ, XOM) for ESG review with
  cited evidence.
- **Robert**, 59, healthcare professional, near retirement. Risk LOW–MODERATE, horizon 3–5 yrs.
  Capital preservation with some growth; prefers established companies; little interest in
  crypto; may be tempted by a hyped stock (e.g., NVDA, TSLA).
  Test: challenge a request that conflicts with his profile, explain the risk, don't just agree.
  Assumed limits: crypto 0%, single stock ≤ 10%, annualized vol ≤ 10%, bonds/cash ≥ 50%,
  max drawdown in 2022 stress ≤ 15%.

All persona data lives in `personas.py`. Profiles are fictional.

## Goal (current)
A CHATBOT. The user picks the persona that best fits their investment profile (Amira, Mateo,
Robert), then chats with it: asks questions in plain language, follow-ups included. For each
question the system recommends a SPECIFIC INDUSTRY/SECTOR (e.g. Utilities, Consumer Staples,
Information Technology, Bonds) that fits the persona, with detailed reasons backed by data:
sector risk numbers, example assets from the universe, how it fits the persona's horizon,
risk tolerance and preferences, and what could go wrong. If the question conflicts with the
persona (e.g. Robert asking about crypto), the bot says so and explains why.
Everything is framed as an educational simulation for a fictional persona, never personal advice.

## User flow
1. Pick a persona (Amira, Mateo, Robert).
2. Chat: ask a question ("Where should I look for growth?", "Is tech too risky for me?",
   "Can I put money in NVDA?"). The conversation keeps context across turns.
3. Each answer: recommended industry/sector + reasons (facts with sources, assumptions,
   risks/limitations) + example assets in that sector + any profile conflicts flagged.
   The full trace (who did what, with which data) is available for every answer.

## Agent pipeline (boss → workers → reviewer → presenter)
```
User (persona + request)
  → BOSS (LLM, Sonnet 5): builds a plan (tickers, checks, order), dispatches workers
  → WORKERS (deterministic Python scripts, NOT LLMs):
       data_retriever   → prices in CAD, FX, macro, asset info + source + period
       risk_analyst     → per asset AND per sector: return, vol, max drawdown, correlation,
                          2022 stress test, risk label (sector = equal-weight basket of the
                          sector's assets in assets_universe.csv; document this)
       market_context   → business-cycle phase (FRED rules), sector momentum/trend/relative
                          strength (from prices), fear vs hope (VIX, credit spreads, sentiment)
       suitability      → compare results to persona limits, flag conflicts with numbers
       news_sentiment (LATER) → headlines (AgentCore Web Search / yfinance) scored fear/neutral/
                          hope by Claude Haiku 4.5 structured output, per sector, cited URLs
       ethics (LATER)   → curated esg_evidence.csv + AgentCore Web Search, cited URLs
  → REVIEWER: checks the work; on FAIL sends the task back to the worker/boss with reasons
       (max 2 retries, then proceed with an explicit "incomplete" note)
  → PRESENTER (LLM, Sonnet 5): writes the final answer using ONLY worker outputs
```
- Boss: Strands Agent whose tools are the worker functions (wrapped with @tool). It keeps the
  chat history (multi-turn) for the session.
- Workers live in `workers/` (one file each). Each returns a dict with `status`, `data`,
  `source`, `period`, `currency`, and `warnings`; on bad input `{"status": "error", "error": ...}`,
  never raise.
- Reviewer (`reviewer.py`): mostly deterministic checks: every requested ticker analyzed,
  every number has source + period, all persona limits evaluated, no data dated after the
  analysis date. Optional small LLM check (Haiku 4.5) that the presenter text matches the
  numbers. Returns `{"verdict": "pass"|"fail", "reasons": [...]}`.
- Presenter: tags each claim `fact` (source + trace step), `assumption`, or `scenario`;
  includes limitations and the simulation/no-advice disclaimer.
- Every step appends to a run trace (step, actor, input, output summary, timestamp), saved as
  JSON locally and to `s3://$DATA_BUCKET/runs/`. The trace is the explainability evidence.
- Bedrock Guardrail on user input and LLM output (personalized advice to the real user, real
  trades, PII). Persona-fit rules stay in `suitability`, not the guardrail.

## Risk labels (team assumption, document in README)
Annualized volatility (adj_close daily returns; 252 days, crypto 365):
< 10% Low · 10–20% Moderate · 20–35% High · > 35% Very High.
Max drawdown is a second check: if max drawdown is worse than -30%, bump the label up one level.

## Data plan (by tier)
Every source must be documented in the README: origin, URL, retrieval date, processing,
license/terms, limitations.

**Tier 1 (now, phases 1–3)**
- Starter CSVs (prices, FX, macro, dividends, universe). Core of all risk numbers.
- Extra FRED series via `data/fetch_fred_extra.py` → `data/macro_extra.csv` (same long format
  as macro_rates.csv: date, series_id, value, unit, frequency, label, source):
  `T10Y2Y` (10y-2y yield curve), `SAHMREALTIME` (Sahm rule recession indicator),
  `RECPROUSM156N` (smoothed recession probability), `INDPRO` (industrial production),
  `VIXCLS` (VIX, fear gauge), `BAMLH0A0HYM2` (high-yield credit spread), `UMCSENT`
  (consumer sentiment). Monthly series: only usable from their publication date (assume
  ~3 weeks after the reference month unless the source gives a release date).
- Price-derived sector signals (no new data): 6- and 12-month momentum, relative strength vs
  XIU.TO (Canada) / SPY (U.S.), price vs 200-day average, current drawdown from peak.

**Tier 2 (after the chatbot works, phases 4–5)**
- AgentCore Web Search for news (URLs + dates must be displayed) + Claude Haiku sentiment.
- yfinance `Ticker.news` as a small "current headlines" bonus (current only, Yahoo terms).
- Curated `data/esg_evidence.csv` (ticker, issue, category, summary, source_name, url,
  published_date, retrieved_date), hand-verified, committed to git.

**Tier 3 (if time allows)**
- SEC EDGAR fundamentals via `fetch_fundamentals.py` (already written; keeps filing dates).
- GDELT news tone (free API) as an extra fear/hope signal.

**Do not use**: Kaggle datasets without a clear license and provenance; Twitter/X (paid,
restricted API); CNN Fear & Greed (proprietary). Scraping news sites (terms of use).

## Market context rules (team assumptions, document; historical tendencies, NOT predictions)
Business-cycle phase from FRED (use only values published by the analysis date):
- **Recession risk** if SAHMREALTIME ≥ 0.5 or RECPROUSM156N ≥ 30%.
- **Late cycle** if T10Y2Y < 0 (inverted) or has been inverted in the past 12 months, and no
  recession signal.
- **Early cycle** if a recession signal was active in the past 12 months and INDPRO is rising.
- **Mid cycle** otherwise.

Sector rotation tendencies: Early → Financials, Consumer Discretionary, Industrials;
Mid → Information Technology, Industrials, Communication Services; Late → Energy,
Health Care, Consumer Staples; Recession → Utilities, Consumer Staples, Health Care, Bonds.
Fear vs hope: VIX < 15 calm/hope, 15–25 normal, > 25 fear; rising credit spreads = stress.
Always present the phase and sector tilt as "historically, sectors like X have tended to…",
labelled `assumption`, with the signal values and dates that triggered it.

## Ethics data
The starter dataset has NO ESG/ethics data (only the ESGV ticker and `sector`). Energy-sector
names (ENB.TO, CNQ.TO, XOM) are candidates for review. Ethics worker comes later (Tier 2).

## UI
Not now. For now the chatbot runs in the terminal (`chat.py`). Streamlit comes in phase 6.

## Testing (required for EVERY phase, before moving on)
Each phase is only done when its tests pass and the results are sanity-checked:
- **Unit tests** (pytest) for every worker function: normal cases, edge cases (unknown ticker,
  empty date range, single asset, crypto 7-day calendar, USD→CAD conversion), error dicts.
- **Data sanity checks**: numbers must be plausible (e.g. bond ETFs XBB.TO/AGG vol well below
  equity vol; BTC-USD vol far above SPY; 2022 return negative for SPY, QQQ, TLT; weights sum
  to 1). Cross-check at least one metric by hand computation in the test.
- **No look-ahead**: tests that results never use data after the requested end date.
- **Pipeline tests** (from phase 3): run the demo questions end to end; check the reviewer
  catches a deliberately incomplete worker output and triggers a retry; check the answer
  only cites numbers that appear in the trace.
- Print a short test report at the end of each phase. Then commit, push, and STOP.

## Build phases (one phase at a time: build → test extensively → commit → stop and wait)
1. **Foundations**: requirements.txt, README skeleton, personas.py, workers/data_retriever.py,
   workers/risk_analyst.py (asset + sector metrics, 2022 stress test, risk labels), tests.
2. **Suitability + market context**: workers/suitability.py (checks a sector or asset against
   the persona limits and preferences, pass/flag per rule with the numbers) and
   workers/market_context.py (cycle phase, sector momentum/trend, fear vs hope) using
   data/fetch_fred_extra.py. Tests for each persona and for each cycle rule.
3. **Chat pipeline**: Strands boss agent with workers as @tool functions, reviewer.py with the
   retry loop (max 2), presenter (Sonnet 5), run trace saved locally + to S3, and chat.py: a
   terminal chatbot (pick persona, then multi-turn Q&A). Verify on the demo questions below.
4. **Guardrail**: attach the Bedrock Guardrail (ID/version from .env) to LLM calls; test that
   persona questions pass and real-user advice / trade requests are blocked.
5. **News + ethics workers**: AgentCore Web Search gateway; news_sentiment worker (Haiku
   structured output, fear/neutral/hope per sector); ethics worker using data/esg_evidence.csv
   + web search, flags Energy-sector names for Mateo with cited evidence.
6. **UI**: Streamlit chat UI on top of the pipeline (persona picker, chat, charts, trace panel).
7. **Docs**: README (sources, licenses, assumptions, limitations), technical doc, one-pager.

Demo questions (must work by the end of phase 3):
- Robert: "I want to put a big part of my savings in NVDA, good idea?" → challenged with numbers;
  steered toward sectors that fit (e.g. Consumer Staples, Utilities, bonds) with reasons.
- Amira: "I only want AI and crypto, which industry should I focus on?" → tech recommended but
  diversification enforced; explains crypto limits.
- Mateo: "Which industry gives balanced growth for me?" → balanced recommendation; Energy
  flagged for ESG review.

## Data (starter dataset, in `data/`, gitignored; do not commit CSVs)
Files: assets_universe.csv, prices_daily.csv, corporate_actions.csv, fx_usdcad_daily.csv,
macro_rates.csv, sources_metadata.csv. Window 2021-11-12 → 2026-11-12.
- Use `adj_close` for returns. Prices are in listing currency: `.TO` = CAD, others USD.
- Convert USD → CAD with fx_usdcad_daily.csv (`usdcad` = CAD per 1 USD) using
  `pd.merge_asof(..., direction="backward")` (FX has no rows on Canadian holidays).
- No calendar alignment in the raw data. Crypto trades 7 days/week (use 365 for annualizing
  crypto, 252 for others) — or align to a common business-day calendar and say so.
- Monthly macro is dated to the reference month, not release date. Assume CPI is published
  ~3 weeks after month end; never use a value before it was published.
- Extra data files (macro_extra.csv, fundamentals.csv, ...) also go in data/ and to S3;
  esg_evidence.csv is the only extra CSV committed to git (add `!data/esg_evidence.csv`).
- Known caveats to state in README: survivorship bias (universe picked in 2026), FRED values are
  revised vintages, CNQ.TO 1.021 "split" on 2022-08-22 is likely a special distribution,
  no ESG/news/fundamentals in the starter set.
- Data also uploaded to S3 (bucket name in `.env` as `DATA_BUCKET`); app can load from S3 or local.

## AWS conventions
- Region: `us-east-1`, always.
- Bedrock via boto3 Converse API (never InvokeModel). Use `global.` inference profile IDs.
- Models: default `global.amazon.nova-2-lite-v1:0` for cheap tests;
  `global.anthropic.claude-sonnet-5` for the agent; `global.anthropic.claude-haiku-4-5-20251001-v1:0`
  for structured output. NOT available: Sonnet 5.5, Haiku 5.5, Fable.
- Sonnet 5 / Opus 5 / Opus 5.5: do NOT pass `temperature` or `topP`; set `maxTokens` ≥ 1000
  (they reason first; too small → empty text, stopReason `max_tokens`).
- Never read `content[0]["text"]`. Always: `"".join(b["text"] for b in blocks if "text" in b)`.
- Structured output: `outputConfig.textFormat.structure.jsonSchema.schema` is a JSON *string*
  (`json.dumps`), `additionalProperties: false` required. Nova 2 Lite does not support it.
- boto3 client config: `Config(retries={"max_attempts": 5, "mode": "adaptive"})`.
- Strands: always pass the model explicitly; cap loops with `agent(..., limits={"turns": 8})`.
  Tool names must match `^[a-zA-Z0-9_-]+$`. Tools return `{"erreur": ...}`-style dicts on failure,
  never raise.
- No Bedrock Agents Classic, no Bedrock Flows, no AgentCore deploy unless everything else works.
- Credentials come from the environment (Workshop Studio temp creds or CloudShell/Kiro).
  NEVER write AWS keys into code, `.env` committed files, or the repo.

## Code conventions
- Python 3.11+. Keep it simple: a working demo beats abstractions.
- Every number shown to the user carries its source, period, and currency.
- Every tool result includes a `source` field and the date range actually used.
- Prompts and system prompts live in `prompts/` as text files, not inline strings.

## Commands
- Install: `pip install -r requirements.txt`
- Chat (terminal, phases 3–5): `python chat.py`
- UI (phase 6): `streamlit run app.py --server.address localhost`
- Test: `python -m pytest -q`
