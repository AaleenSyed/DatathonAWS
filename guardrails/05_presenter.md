# 5. Presenter (LLM on Bedrock, streamed)

## Role
Write the final answer from worker outputs only. Model from `PRESENTER_MODEL` (`presenter.py`); prompt
`prompts/presenter_system.txt` plus `prompts/lang_<code>.txt`.

## May
- Recommend a **sector/industry** that fits the persona, with example assets from the universe.
- Explain persona conflicts and challenge the request instead of just agreeing (e.g. Robert + NVDA).

## Must
- Use **only** numbers and facts present in the trace. No outside knowledge presented as fact.
- Tag each claim `fact` (`[fact: step N]`), `assumption`, or `scenario`.
- For a recommendation, include risk numbers, horizon fit, and what could go wrong.
- State persona conflicts clearly and explain why.
- Include limitations. The disclaimer is added by code if missing (`texts.py`, EN/FR):
  *"Educational simulation for a fictional persona (Name). Not personalized financial advice."*

- Take every comparison or rank from the `compare_metrics` step (`comparisons.py`: ranks and ready-made
  sentences computed in Python, e.g. "Utilities has the lowest annualized volatility ... (14.7%), Financials
  2nd (15.7%)"); a value vs a persona limit is stated as the suitability check gives it.
- Copy each suitability status exactly as the trace gives it for that target and rule.
## Must not
- Compare or rank numbers itself.
- Relabel a status (a pass is never "info", a flag never "info", an info never a "conflict").
- Add concepts or claims that are not in the trace (e.g. "survivorship bias", "recoverable" losses, what
  credit spreads tend to favour). Limitations come from the trace warnings and periods only.
- Address the real user as the investor ("you should buy…"). Speak about the persona.
- Promise or predict returns ("will go up", "guaranteed", "safe bet").
- Give position sizes or trade instructions beyond the persona's documented limits.
- Hide the Reviewer's "incomplete" note (the pipeline prepends it in code).
- Drop worker warnings the user needs, e.g. "sector = 1 asset, not diversified".

## Input checks
- Reads the worker steps of the run trace, the Boss plan, and any "incomplete analysis" note.

## Output checks
- Every number appears in the trace and no return is promised or predicted (Reviewer `check_answer`).
- Comparative words match the order of their numbers, and status words match the trace (Reviewer `check_answer`).
- Disclaimer present (code).
- Citations point to real worker/user steps (Reviewer). That *every* claim is tagged is prompt-only.
- Output Bedrock Guardrail passes (when configured).

## On failure
- Reviewer `check_answer` fails → the draft is rewritten once with the reasons (`MAX_ANSWER_RETRIES = 1`);
  still failing → shown with a "Reviewer note".
- Output Bedrock Guardrail blocks → the user gets the polite block message from
  [01_bedrock_guardrail.md](01_bedrock_guardrail.md).

## Enforced by
- `prompts/presenter_system.txt`
- Reviewer `check_answer` (numbers, citations, no predictions)
- `pipeline.py` (disclaimer, incomplete note, output guardrail)
- Tests: every number in the answer is found in the trace; prediction wording fails
  (`tests/test_pipeline.py`, `tests/test_reviewer.py`)

## Not yet enforced in code (prompt only)
- Keeping the "sector = 1 asset, not diversified" warning, the limitations section, and speaking about the
  persona rather than the user.
- No concepts or claims outside the trace (the reviewer checks numbers, comparisons and statuses, not ideas).
