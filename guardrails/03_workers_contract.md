# 3. Workers: Shared Contract (deterministic Python, not LLMs)

Applies to every worker in this folder. Each `03_workers_*.md` file adds its own rules on top of this contract.

## Role
Do one well-defined job (load data, compute risk, classify context, check suitability) and return
a structured, sourced result.

## May
- Read from `data/` (local or S3 copy).
- Call only the documented APIs listed in the individual worker files. No other network calls.

## Must not
- Raise exceptions. Errors are returned, never raised.
- Use data dated after the analysis end date.
- Hide data-quality issues.
- Produce any value from memory or hard-coded facts (see `00_global.md`).

## Return contract

Success:
```json
{"status": "ok", "data": {...}, "source": "...", "period": {"start": "...", "end": "..."}, "currency": "...", "warnings": [...]}
```

Bad input:
```json
{"status": "error", "error": "..."}
```

`currency` is set where the result holds money, prices or returns (`"CAD"` or `"USD"`); it is `null` for
results without a currency (macro signals in `cycle_phase` / `fear_hope`, `list_sectors`).

## Input checks
- Inputs are validated before work starts (ticker, dates, persona, as relevant per worker).
- Rows after the analysis end date are dropped.

## Output checks
- `source` and `period` are present on every result; `currency` where relevant (see above).
- When rows after the end date were dropped, `warnings` says so ("rows dated after the end date … were
  excluded (no look-ahead)"). No row count: it would change when newer data is appended, and results must not.
- Data-quality issues (missing days, short history, FX gaps) are listed in `warnings`.

## On failure
Return `{"status": "error", "error": "<reason>"}`. Never raise. The Boss decides whether to retry.

## Enforced by
- Code (`_ok` / `_err` helpers in each worker; `agent_tools._run` catches anything that slips through)
- Pure functions (same input → same output), tested with pytest
- Reviewer checks 2, 4, and 5 (`04_reviewer.md`)
- Tests: unknown ticker / empty range → `status: error`; results unchanged when data after the
  end date is appended; dropped rows reported (`test_rows_after_end_are_reported_not_hidden`)
