# 0. Global Rules (apply to every agent)

**Scope:** Bedrock Guardrail, Boss, all Workers, Reviewer, Presenter.

| Rule | Enforced by |
|---|---|
| Simulation only. No real trades, no order placement, no broker/API calls that move money. | No such tool exists (`agent_tools.TOOLS`); Bedrock Guardrail denied topic "real trades" |
| Advice is for a **fictional persona** only, never personalized advice to the real user. | Presenter prompt; disclaimer always appended by code (`pipeline.py`, `texts.py`); Bedrock Guardrail denied topic "personal financial advice" |
| No PII collected, stored, or echoed (names, SIN/SSN, account numbers, emails, phone). | `guardrail.redact_pii` masks e-mails, phone numbers, SIN, card and IBAN-like numbers before the question, boss prompts and answers are written to the run trace (local + S3); Bedrock Guardrail PII filter on input and output when configured |
| All LLM calls go through Amazon Bedrock (`us-east-1`, `global.` profiles). No other provider, no `ANTHROPIC_API_KEY`. | Code review: the only model clients are the Strands `BedrockModel` (boss, `pipeline.py`) and boto3 `bedrock-runtime` (presenter `presenter.py`, guardrail `guardrail.py`) |
| No look-ahead: no data dated after the analysis date; monthly macro only after its publication date. | Tools pin the end date to the session's analysis date (`agent_tools.CONTEXT`); workers filter by date; reviewer re-checks |
| Every number carries `source` and `period`, and `currency` where it is money or a price. | Worker return contract; reviewer check |
| **No facts from memory.** Every value (price, return, rate, date, ticker, sector, source, URL) comes from `data/` files or a script/worker that was run, never from an agent's own knowledge. Only exception: rules and thresholds written in `CLAUDE.md` / this folder, cited. Missing value → "not available" + reason, never a guess. | Workers read only data/scripts; presenter uses only trace numbers; reviewer checks every number exists in the trace; tests compute expectations from data or synthetic series |
| Every step is logged to the run trace (step, actor, input, output summary, timestamp). | `run_trace.py`; trace saved locally + `s3://$DATA_BUCKET/runs/` |
| No credentials in code, prompts, traces, or logs. | `.gitignore`, `git status` before commit; traces never include env vars |
| Bounded execution: Strands `limits={"turns": 4}` (`pipeline.BOSS_LIMITS`), reviewer max 2 retries, answer check max 1 retry, boto3 adaptive retries (5). | Code |

## Personas

Valid personas: **Amira, Mateo, Robert**. Limits and preferences are defined only in `personas.py`.
No agent may change them at runtime. A persona switch happens only through the explicit persona picker
(the persona is fixed per `ChatSession` and passed to the tools through `agent_tools.CONTEXT`, never by the LLM).

## Trace entry (minimum fields)

| Field | Content |
|---|---|
| `step` | Sequential step number |
| `actor` | Agent or worker name (`user`, `guardrail`, `boss`, `worker:<name>`, `reviewer`, `presenter`, `pipeline`) |
| `input` | Input summary (PII-redacted, no credentials) |
| `output_summary` | Result summary, including `status` and `warnings` |
| `timestamp` | Time of the step |
