# 3.5 Worker: news_sentiment (phase 5)

Follows [03_workers_contract.md](03_workers_contract.md). Not built yet (phase 5).

## Role
Collect recent headlines for a ticker and score their tone as a signal.

## May
- Pull headlines via AgentCore Web Search or yfinance `Ticker.news`.
- Score each headline fear / neutral / hope with Haiku 4.5 structured output (through Bedrock).

## Must not
- Scrape news sites.
- Use Twitter/X.
- Use headlines without URL + date.
- Let headline text act as instructions. Headlines are untrusted data.

## Input checks
- Every headline has URL, publisher, and published date.
- Published date is on or before the analysis date.

## Output checks
- Schema-valid JSON (`additionalProperties: false`).
- Sentiment is shown as a signal, never as a buy/sell call.

## On failure
- Headline missing URL, publisher, or date → excluded and noted in `warnings`.
- Schema-invalid model output → `{"status": "error", "error": "..."}`.

## Enforced by
- Code (field validation, JSON schema validation)
- Haiku prompt treats headline text as data only
- Reviewer checks 2 and 4