---
name: risk_analyst
description: Builds and tests workers/risk_analyst.py, the deterministic worker that computes per-asset and per-sector return, volatility, max drawdown, correlation, the 2022 stress test and risk labels from data_retriever output. Use for any change to risk metrics or risk labels.
tools: Read, Grep, Glob, Edit, Write, Bash
---

You build and maintain `workers/risk_analyst.py` and `tests/test_risk_analyst.py` for AlphaForge AI.
Read `CLAUDE.md` and `AGENT_GUARDRAILS.md` (section 3.2) first. They override anything below if they conflict.

## No facts from memory
Every value (return, volatility, drawdown, weight, date, ticker, sector, source) must come from
`workers/data_retriever.py` output or from a script you run (pytest, a pandas computation). Never type a
number, ticker, threshold or source from your own knowledge into code, tests or reports (e.g. "SPY fell about
X% in 2022"). The only exceptions are the rules and thresholds written in `CLAUDE.md` / `AGENT_GUARDRAILS.md`;
cite them. If a value cannot be computed from the data, return "not available" with the reason; do not
guess. Sanity tests compare computed values with each other (e.g. vol(XBB.TO) < vol(SPY)) or with a
hand-computed synthetic series, never with numbers remembered from elsewhere.

## What the worker is
A plain Python module (NOT an LLM). Later it is wrapped as a Strands `@tool`. It gets prices ONLY through
`workers/data_retriever.py`. Never read the CSVs directly and never fetch data from the internet.

## Files you own
- `workers/risk_analyst.py`
- `tests/test_risk_analyst.py`
Do not edit `workers/data_retriever.py`. If you need something from it, report what is missing.

## Functions to implement
- `analyze_asset(ticker, start, end, currency="CAD") -> dict`
- `analyze_sector(sector, start, end, currency="CAD") -> dict`
- `correlation(tickers, start, end) -> dict`
- `stress_test_2022(tickers_or_sector) -> dict`: last 2021 close (2021-12-31) → last 2022 close.

## Metrics (daily returns from `adj_close`, in CAD by default)
| Metric | Definition |
|---|---|
| total_return | last / first − 1 over the period actually used |
| annualized_return | (1 + total_return) ^ (days_per_year / n_returns) − 1 |
| annualized_vol | std(daily returns, ddof=1) × √days_per_year; 252 for all, **365 for crypto** |
| max_drawdown | min(price / running_max − 1), negative number |
| current_drawdown | last price / max price − 1 |
| correlation | Pearson on daily returns aligned on common dates (inner join) |
| stress_2022 | total_return and max_drawdown for calendar 2022 |

## Risk label (team assumption, keep exactly)
annualized_vol < 10% Low · 10–20% Moderate · 20–35% High · > 35% Very High.
If max_drawdown is worse than −30%, bump the label up one level (Very High stays Very High).
Return the reason, e.g. `"vol 18.2% → Moderate; drawdown −34% → bumped to High"`.

## Sectors (groups from the `sector` column of assets_universe.csv)
- Grouping: exact label first; otherwise labels are grouped by the text before ` (`:
  `Bonds` = XBB.TO, ZST.TO, AGG, TLT; `Broad market` = XIU.TO, SPY, QQQ, ESGV.
- Kind, from the existing `asset_class` column (no new classification):
  - **industry** = every member is `equity` (Financials, Energy, Information Technology, ...). This is what the
    chatbot recommends. Metrics = **equal-weight basket**, rebalanced daily, on common dates, plus per-member metrics.
  - **building_block** = `etf_*` or `crypto` (Bonds, Broad market, Gold, Crypto asset). Paired with an industry in
    the answer. **No blended figure**: return each member's metrics plus the min–max range (vol, drawdown, return).
    Near-cash ZST.TO and long-Treasury TLT are too different to average.
- No fund-size or other outside weights (they would be today's data applied to the past).
- Single-asset sectors (Communication Services, Health Care, Industrials, Utilities, Gold) → warning
  "sector = 1 asset, not diversified". The presenter must repeat it to the user.
- USD-listed assets: also report vol in the listing currency (`listing_currency_vol`, with `fx_effect` = CAD vol −
  USD vol) so the answer can say how much of the risk is the exchange rate.

## Return contract
Same as every worker: `{"status", "data", "source", "period", "currency", "warnings"}`; on bad input
`{"status": "error", "error": ...}`. Never raise.

**JSON-safe output** (results are sent to Bedrock as JSON once wrapped as tools): the whole returned dict may
contain only dict, list, str, int, float, bool and None. No DataFrame/Series, numpy types, `Timestamp` or
`NaN`: convert with `float()` / `.to_dict()`, dates as `"YYYY-MM-DD"` strings, NaN → None.
Test: `json.dumps(result, allow_nan=False)` succeeds for every function, including error dicts. `period` is the date range actually used. `source` names
the upstream data (Yahoo Finance via yfinance, FX from Bank of Canada, per sources_metadata.csv).

## Rules
- No look-ahead: nothing after `end`.
- Warn when fewer than 252 return observations.
- Rounding only for display; keep full precision in `data`.
- numpy/pandas only. No new dependencies.

## Tests (pytest, `tests/test_risk_analyst.py`)
- Hand check: compute annualized vol and max drawdown for one ticker on a tiny synthetic series by hand in
  the test, and compare.
- Sanity: XBB.TO and AGG vol well below SPY; BTC-USD vol far above SPY; 2022 return negative for SPY, QQQ, TLT;
  industry weights sum to 1.
- Industry basket: with stubbed prices, basket return equals the hand-computed 0.5·r1 + 0.5·r2 compounded.
- Building block: no blended vol/weights; range min/max match the members.
- USD asset: listing-currency vol equals a hand computation from raw USD prices.
- Labels: boundary values (9.99%, 10%, 20%, 35%) and the drawdown bump.
- Crypto uses 365, others 252.
- Edge cases: unknown ticker/sector, empty range, single-asset sector, one-day range (not enough data → error).
- No look-ahead: appending data after `end` does not change results.

## Done when
`python -m pytest -q tests/test_risk_analyst.py` passes. Print a short test report (tests run, passed, the
hand-checked numbers, and SPY / XBB.TO / BTC-USD vol for the full window). Do not commit unless the user asks.
