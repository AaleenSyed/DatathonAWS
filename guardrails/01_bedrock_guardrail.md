# 1. Bedrock Guardrail (input + output filter)

## Role
First and last filter around the LLM calls. It checks the user's question before the Boss and the final
answer after the Presenter. Implemented in `guardrail.py` with the Bedrock **ApplyGuardrail** API and called
from `pipeline.ChatSession.ask`.

## Configuration
- `GUARDRAIL_ID` and `GUARDRAIL_VERSION` (default `DRAFT`) come from the environment / `.env`.
- The guardrail itself (denied topics, PII, content and prompt-attack filters below) is created in the AWS
  console; the code only applies it.
- **Off** (no AWS call, no trace step) when `GUARDRAIL_ID` is unset or `AGENT_MODE=demo`.

## May
- **Block denied topics:**
  - personalized advice to the real user ("what should *I* buy with *my* savings")
  - requests to execute real trades or connect to a brokerage
  - tax/legal advice presented as authoritative
  - market-manipulation or insider-trading content
- **Handle PII:** block or mask names, emails, phone numbers, account/card numbers, SIN/SSN.
- **Apply content filters:** hate, insults, sexual, violence, misconduct.
- **Apply the prompt-attack filter** to user input.

## Must not
- Decide persona fit (e.g. "Robert wants NVDA"). That is the `suitability` worker's job, so the bot can
  *explain* the conflict instead of refusing.
- Block the demo questions. They are written in the first person ("I want to put a big part of my savings in
  NVDA") because the user speaks *as* the persona: tune the denied-topic definitions and examples so that
  persona questions pass, input and output (see `06_tests.md`).
- Log raw PII from a blocked request.

## Input checks (user → Boss)
- Denied topics
- PII filter
- Content filters
- Prompt-attack filter

## Output checks (final answer → user)
- Denied topics (e.g. text that reads as personal advice or trade instructions)
- PII filter
- Content filters
- The checked text is the full final answer, notes and disclaimer included.

## On failure
- **Block (`GUARDRAIL_INTERVENED`):** the user gets the polite `guardrail_block` message (`texts.py`, EN and
  FR) explaining the tool is an educational simulation for fictional personas. Input block: the Boss and the
  Presenter are not called. Output block: the drafted answer is replaced (and cleared from the stream).
- The trace records a `guardrail` step (`input_blocked` / `output_blocked`) with PII-redacted text and only
  the names of the policies that fired, never the matched content. Verdicts are `"blocked"`.
- **API error:** fail open (the run continues) and log a `guardrail` step with `status: error`. Persona-fit
  rules never depend on the guardrail.
- A pass is logged as `input_checked` / `output_checked`.

## Enforced by
- `guardrail.py` (`configured`, `check`, `redact_pii`), `pipeline.ChatSession._guard`
- Bedrock Guardrail configuration (ID/version from `.env`)
- Tests: `tests/test_guardrail.py`, `tests/test_pipeline.py` (mocked: blocked input → polite message, Boss not
  called, no raw PII in trace; blocked output → polite message; unset ID / demo mode → no call).
  Live check still to do once a guardrail ID exists: demo questions pass; "buy NVDA for me with my $50k",
  trade requests, PII → blocked.
