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

## Architecture
1. **Analyst agent**: Strands Agents + Amazon Bedrock. Tools (all math in pandas, never the LLM):
   - `risk_metrics(ticker, start, end)`: total return, annualized vol, max drawdown, in CAD.
   - `simulate_portfolio(weights, start, end)`: portfolio vol, drawdown, correlation matrix,
     2022 stress-test result.
   - `macro_context(as_of)`: BoC/Fed rates, yields, CPI, only values published by `as_of`.
   - `esg_evidence(company)`: AgentCore Web Search (added later), returns cited URLs + dates.
2. **Governance check**: deterministic Python in `governance.py`. Checks a proposed allocation
   or request against persona limits + simulation boundaries; returns pass/flag per rule with
   the numbers. Plus a Bedrock Guardrail (denied topics: personalized advice, real trades; PII).
3. **Explainer**: Claude Haiku 4.5 with structured output (JSON schema). Every claim tagged
   `fact` (with source + trace step), `assumption`, or `scenario`. Includes limitations.
4. **UI**: Streamlit. Persona cards, request box, charts (plotly), governance panel,
   agent trace (tool, args, result), "what-if" sensitivity control.

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
- Run: `streamlit run app.py --server.address localhost`
- Test: `python -m pytest -q`
