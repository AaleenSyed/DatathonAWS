# 3.3 Worker: market_context

Follows [03_workers_contract.md](03_workers_contract.md).

## Role
Describe the market backdrop: cycle phase, sector momentum, relative strength, and fear/hope signals.

## May
- Classify the cycle phase using the FRED rules in `CLAUDE.md`.
- Compute sector momentum (6m / 12m).
- Compute relative strength vs XIU.TO / SPY.
- Compute price vs 200-day average.
- Report VIX and credit-spread fear/hope signals.

## Must not
- Present the phase or sector tilt as a prediction.

## Input checks
- Uses only series values published by the analysis date (monthly macro respects publication lag).

## Output checks
- Output is labelled `assumption` (`claim_type`).
- Includes the triggering signal values and their dates.
- States which rule fired (`rule_fired`).

## On failure
- Missing series → `{"status": "error", "error": "..."}`, or the affected signal is marked
  "not available" with the reason in `warnings`. Never guessed.

## Enforced by
- Code (date filter, rule table from `CLAUDE.md`)
- pytest: appended future data does not change momentum (`test_momentum_no_look_ahead`) or the phase
  (`test_cycle_phase_no_look_ahead`)
- Reviewer check 4 (no look-ahead)
