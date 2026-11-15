# 3.2 Worker: risk_analyst

Follows [03_workers_contract.md](03_workers_contract.md).

## Role
Compute risk and return metrics and assign a risk label.

## May
- Compute return, annualized volatility (252 days; 365 for crypto), max drawdown, correlation,
  the 2022 stress test, and the risk label.
- **Industries (all-equity groups):** use an equal-weight basket.
- **Building blocks (ETFs, crypto):** report per-member metrics plus a min–max range, no blended figure.
- For USD assets, also report volatility in USD.

## Must not
- Change the risk-label thresholds without updating the README:

| Annualized vol | Label |
|---|---|
| < 10% | Low |
| 10–20% | Moderate |
| 20–35% | High |
| > 35% | Very High |

  A max drawdown worse than −30% bumps the label up one level.

## Input checks
- Price data comes from `data_retriever` with `source`, `period`, `currency`.
- Warn if there is less than about 1 year of data (`SHORT_HISTORY_DAYS`).
- One-asset groups carry the warning "sector = 1 asset, not diversified".

## Output checks (sanity)
These are checked by the **test suite** on the real data (`tests/test_risk_analyst.py`), not at runtime:
- Bond ETF vol < equity vol.
- BTC vol > SPY vol.
- Basket weights sum to 1.

## On failure
- Bad or missing input → `{"status": "error", "error": "..."}`
- Short history → reported in `warnings`, never hidden.

## Enforced by
- Code (thresholds defined once in `risk_label` and cited in README)
- pytest sanity tests using data or synthetic series
- Reviewer check 2 (every result sourced)
