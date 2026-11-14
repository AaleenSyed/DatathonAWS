# AlphaForge AI: PolyFinances Datathon 2026

Self-explaining agentic decision-support chatbot. Pick a fictional investor persona (Amira, Mateo, Robert),
ask a question, and the system recommends a sector that fits the persona, with risk numbers, sources,
assumptions and limitations.

> **Educational simulation for fictional personas. Not personalized financial advice. No real transactions.**

## Status
- [x] Phase 1: personas, data_retriever, risk_analyst, tests
- [ ] Phase 2: suitability + market context
- [ ] Phase 3: chat pipeline (boss, reviewer, presenter, trace)
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
```
Data CSVs go in `data/` (gitignored) or are read from `s3://$DATA_BUCKET/data/` (set `DATA_BUCKET` in `.env`).
AWS credentials come from the environment / `~/.aws/credentials`, never from the repo.

## Architecture
See `CLAUDE.md` (pipeline) and `AGENT_GUARDRAILS.md` (guardrails per agent). Agent definitions: `agents/`.

| File | Role |
|---|---|
| `personas.py` | Fictional personas and their limits |
| `workers/data_retriever.py` | Prices (adj_close, USD→CAD), FX, macro (publication-lag aware), asset info |
| `workers/risk_analyst.py` | Asset/sector return, vol, drawdown, correlation, 2022 stress test, risk labels |

## Data sources
Full list with URLs, retrieval dates, processing, terms and limitations: `data/sources_metadata.csv`.
- Prices, corporate actions: Yahoo Finance via yfinance (Yahoo terms of use)
- USD/CAD FX, Canadian yields, policy rate, CPI: Bank of Canada Valet API
- U.S. rates, CPI, unemployment: FRED (Federal Reserve Bank of St. Louis)
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
- **Monthly macro** counts as published 21 days after the end of its reference month.

## Limitations
- Survivorship bias: the universe was picked in 2026.
- FRED values are revised vintages, not what was known at the time.
- CNQ.TO 1.021 "split" on 2022-08-22 is likely a special distribution.
- Several sectors have only one asset (Communication Services, Health Care, Industrials, Utilities, Gold).
- No ESG, news or fundamentals data in the starter set.
