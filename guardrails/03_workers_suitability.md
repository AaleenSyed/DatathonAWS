# 3.4 Worker: suitability

Follows [03_workers_contract.md](03_workers_contract.md).

## Role
Compare worker results with the active persona's limits and preferences.

## May
- Return a status per rule, with the actual number vs the limit and a plain-language explanation.

## Must not
- Silently relax a limit.
- Skip a limit because data is missing. Report `not_evaluated` with the reason instead.

## Statuses

| Status | Meaning |
|---|---|
| `conflict` | A hard rule is broken **at the proposed weight**: excluded asset type (e.g. crypto for a 0% persona), or a proposed weight above a cap |
| `flag` | The target on its own breaks a portfolio-level limit (standalone volatility or 2022 drawdown above the persona limit), or needs review (ESG) |
| `info` | Portfolio-level reminder: a cap to respect when no weight is proposed ("keep at most 15.0%"), or a minimum still to fill (e.g. bonds ≥ 50%) |
| `pass` | Within the limit |
| `not_applicable` | The rule does not concern this target |
| `not_evaluated` | Data missing (reason given) |

`overall` = the most severe status: `conflict` > `flag` > `incomplete` (some rule `not_evaluated`) > `pass`.

## Input checks
- Active persona is one of Amira / Mateo / Robert, loaded from `personas.py`.
- Risk numbers come from `risk_analyst` results with `source`, `period`, `currency`.

## Output checks
- **Every** limit in `personas.py` for the active persona appears in the output.
- Each entry has a status, the actual value, and the limit.
- Excluded asset types (e.g. Robert or Mateo + crypto) are always `conflict`.
- Caps (e.g. single stock > 10% for Robert): `conflict` at a proposed weight above the cap, `pass` at or
  below it; **without a proposed weight the result is `info`** (a reminder of the cap), not a conflict.
  The boss passes `proposed_weight` when the user states or implies a share ("a big part of my savings" → 50%).

## On failure
- Unknown persona or malformed input → `{"status": "error", "error": "..."}`
- Missing data for a limit → `not_evaluated` + reason (not an error).

## Enforced by
- Code (iterates over all persona limits from `personas.py`)
- pytest (`tests/test_suitability.py`): Robert + NVDA at 50% / crypto → `conflict` with numbers
- Reviewer check 3 (every persona limit evaluated)
