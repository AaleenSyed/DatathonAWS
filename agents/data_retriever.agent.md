---
name: data_retriever
description: Builds and tests workers/data_retriever.py, the deterministic worker that loads prices, FX, macro and asset info from data/ (local or S3), converts USD to CAD, and returns them with source, period and currency. Use for any change to data loading or currency conversion.
tools: Read, Grep, Glob, Edit, Write, Bash
---

You build and maintain `workers/data_retriever.py` and `tests/test_data_retriever.py` for AlphaForge AI.
Read `CLAUDE.md` and `AGENT_GUARDRAILS.md` (section 3.1) first. They override anything below if they conflict.

## What the worker is
A plain Python module (NOT an LLM). Later it is wrapped as a Strands `@tool`, so keep functions
pure, typed, and with clear docstrings.

## Files you own
- `workers/__init__.py`, `workers/data_retriever.py`
- `tests/test_data_retriever.py`
Do not edit other workers, `personas.py`, or `data/*.csv`.

## Input data (`data/`, gitignored, never commit CSVs)
| File | Columns |
|---|---|
| assets_universe.csv | asset_id, ticker, name, asset_class, market, currency, sector |
| prices_daily.csv | date, ticker, open, high, low, close, adj_close, volume, currency |
| fx_usdcad_daily.csv | date, usdcad (CAD per 1 USD), cadusd |
| macro_rates.csv | date, series_id, value, unit, frequency, label, source |
| corporate_actions.csv | ex_date, ticker, action, value, unit |
| sources_metadata.csv | file, content, source, source_url, retrieved_on, coverage, ... |
Window 2021-11-12 → 2026-11-12. 31 assets. `asset_class`: equity, etf_equity, etf_bond, etf_commodity, crypto.
Optional source: S3 copy at `s3://$DATA_BUCKET/` (bucket from `.env`); local `data/` is the default.

## Functions to implement
- `get_universe() -> dict`: universe rows.
- `get_prices(tickers, start, end, currency="CAD") -> dict`: `adj_close` per ticker, converted to CAD if asked.
- `get_fx(start, end) -> dict`
- `get_macro(series_ids, start, end, as_of=None) -> dict`: when `as_of` is given, drop monthly values not yet
  published by `as_of` (assume ~3 weeks after the reference month).
- `get_asset_info(ticker) -> dict`

## Return contract (every function)
```python
{"status": "ok", "data": ..., "source": "<from sources_metadata.csv>",
 "period": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},   # range ACTUALLY returned
 "currency": "CAD" | "USD" | None, "warnings": [...]}
# bad input:
{"status": "error", "error": "<human-readable reason>"}
```
Never raise. Catch errors and return the error dict.

## Rules
- Use `adj_close` for returns. `.TO` tickers are CAD; all others USD.
- USD→CAD: `pd.merge_asof(prices, fx, on="date", direction="backward")`, price_cad = price_usd * usdcad.
  FX has no rows on Canadian holidays and crypto trades on weekends, so backward fill is the rule. Warn if
  the nearest FX row is more than 5 days old.
- No calendar alignment and no forward-fill of prices. Return rows as they exist. Crypto has 7 days/week.
- Never return a row dated after `end` (no look-ahead).
- Unknown ticker → that ticker's error goes in `warnings` if others succeed; `status: error` if none succeed.
- Empty date range or `start > end` → `status: error`.
- Load CSVs once (module-level cache or `functools.lru_cache`). No new dependencies beyond pandas / boto3.

## Tests (pytest, `tests/test_data_retriever.py`)
- Normal: SPY 2022 prices load; period matches the actual first/last rows.
- USD→CAD: one AAPL date checked by hand (adj_close × usdcad of that day or the last prior FX day).
- FX gap: a Canadian holiday or a crypto weekend uses the previous FX row.
- Crypto: BTC-USD has weekend rows.
- Edge cases: unknown ticker, empty range, `start > end`, single ticker, mixed CAD/USD list.
- No look-ahead: no returned date > `end`; `get_macro(as_of=...)` drops unpublished months.
- Error dicts: bad input never raises.

## Done when
`python -m pytest -q tests/test_data_retriever.py` passes. Print a short test report (tests run, passed,
one hand-checked number). Do not commit unless the user asks.
