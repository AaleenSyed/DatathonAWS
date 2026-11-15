# 3.1 Worker: data_retriever

Follows [03_workers_contract.md](03_workers_contract.md).

## Role
Load prices, FX, macro, and universe information for the requested tickers and period.

## May
- Load prices (`adj_close`), FX, macro series, and universe info.
- Convert USD→CAD using `merge_asof(direction="backward")`.

## Must not
- Fetch tickers outside `assets_universe.csv`.
- Forward-fill across long gaps silently (prices are never filled; an FX rate older than the stale limit is
  reported in `warnings`).
- Use macro values before their publication date (~3 weeks after the reference month unless a
  release date exists; `MACRO_PUBLICATION_LAG_DAYS`, `PUBLICATION_LAG_OVERRIDES`).

## Input checks
- Ticker exists in `assets_universe.csv`.
- Requested date range is non-empty and start ≤ end.

## Output checks
- Currency stated.
- The **actual** period returned is reported, not just the requested one.
- Gaps, stale FX and rows dropped after the end date are listed in `warnings`.

## On failure
- Several tickers, some unknown → `status: ok` with the known ones and one warning per unknown ticker
  (`"unknown ticker 'X' (not in assets_universe.csv)"`). Error only if **all** are unknown or have no data.
- One unknown ticker (`get_asset_info`) → `{"status": "error", "error": "unknown ticker 'X' (not in assets_universe.csv)"}`
- No prices in range → `{"status": "error", "error": "X: no prices between <start> and <end>"}`
- No tickers given → `{"status": "error", "error": "no tickers given"}`

## Enforced by
- Code (universe lookup, date filter, publication-lag filter)
- pytest (`tests/test_data_retriever.py`): unknown ticker, mixed known/unknown list, empty range, appended
  future data does not change results, dropped rows reported
- Reviewer check 4 (no data after the analysis date)
