# 4. Reviewer (`reviewer.py`, deterministic)

## Role
Quality gate between workers and Presenter (`review_work`), and check of the Presenter's answer
(`check_answer`). No LLM.

## May
- Run the deterministic checks below on the Boss plan, worker outputs, and trace.
- Check the Presenter draft.
- Send work back to the Boss (or the draft back to the Presenter) with reasons.

## Must not
- Edit worker data or the answer itself.
- Return anything other than `{"verdict": "pass"|"fail", "reasons": [...]}`.

## Input checks
- Receives the Boss plan (`requested_targets`, `recommended_sectors`, conflicts, notes).
- Reads the persona's limits from `personas.py` (not from the plan).
- Receives all worker outputs and the run trace; the Presenter draft for `check_answer`.

## Output checks

**`review_work` (deterministic)**
1. Every ticker/sector named in the question or in the plan was analyzed (risk) and suitability-checked;
   targets outside the universe must be explained in `reasoning_notes`.
2. Every successful worker result has `source` + `period`.
3. Every persona limit was evaluated (any status, `not_evaluated` with a reason).
4. No data dated after the analysis date.
5. No worker returned `status: error` without being retried successfully or explained in `reasoning_notes`.

Extra checks in the code:
- The plan recommends at least one sector group, and each is a real group of the universe.
- Each recommended group has a successful `analyze_sector`, `sector_momentum` and `check_suitability`, and
  its suitability is not `conflict`.
- The market context (`cycle_phase`) was evaluated.
- The persona's ESG-review names (Mateo: ENB.TO, CNQ.TO, XOM) were suitability-checked.

**`check_answer` (deterministic, on the Presenter draft)**
- Every number in the draft exists in the trace (in the cited step when tagged `[fact: step N]`), within
  rounding; French number style is read too.
- Citations point to worker or user steps.
- No promise or prediction of returns ("guaranteed", "will go up / rise / double", "safe bet",
  "garanti", "sans risque", "va monter", ...), unless negated ("not guaranteed", "n'est pas garanti").

An optional LLM check (Haiku 4.5) is not implemented; the deterministic checks cover the same rules.

## On failure
- `review_work` fail → back to the Boss with the reasons. **Max 2 retries.** After that, proceed with an
  explicit "incomplete analysis" note shown to the user and logged in the trace.
- `check_answer` fail → back to the Presenter with the reasons. **Max 1 retry.** After that, the answer is
  shown with a "Reviewer note" listing the reasons.

## Enforced by
- `reviewer.py`
- Pipeline retry counters (`MAX_REVIEW_RETRIES = 2`, `MAX_ANSWER_RETRIES = 1`)
- Tests: deliberately incomplete worker output → `fail` → retry → "incomplete" note after 2
  (`tests/test_pipeline.py`); number, citation and prediction checks (`tests/test_reviewer.py`)
