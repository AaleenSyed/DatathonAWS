# Agent Guardrails: AlphaForge AI

Detailed guardrails for every agent in the pipeline (see `CLAUDE.md`). The short canonical summary is
[`../AGENT_GUARDRAILS.md`](../AGENT_GUARDRAILS.md); these files hold the details.

```
User → Bedrock Guardrail (input) → BOSS → WORKERS → REVIEWER → PRESENTER → Bedrock Guardrail (output) → User
```

## Files

| File | Agent | Type |
|---|---|---|
| [00_global.md](00_global.md) | All agents | Rules |
| [01_bedrock_guardrail.md](01_bedrock_guardrail.md) | Bedrock Guardrail | Managed filter (input + output), `guardrail.py` |
| [02_boss.md](02_boss.md) | Boss | LLM (Strands Agent on Bedrock) |
| [03_workers_contract.md](03_workers_contract.md) | All workers | Shared contract |
| [03_workers_data_retriever.md](03_workers_data_retriever.md) | data_retriever | Deterministic Python |
| [03_workers_risk_analyst.md](03_workers_risk_analyst.md) | risk_analyst | Deterministic Python |
| [03_workers_market_context.md](03_workers_market_context.md) | market_context | Deterministic Python |
| [03_workers_suitability.md](03_workers_suitability.md) | suitability | Deterministic Python |
| [03_workers_news_sentiment.md](03_workers_news_sentiment.md) | news_sentiment (phase 5, not built) | Python + Haiku 4.5 structured output |
| [03_workers_ethics.md](03_workers_ethics.md) | ethics (phase 5, not built) | Python + web search |
| [04_reviewer.md](04_reviewer.md) | Reviewer | Deterministic (`reviewer.py`) |
| [05_presenter.md](05_presenter.md) | Presenter | LLM (Bedrock Converse, streamed) |
| [06_tests.md](06_tests.md) | All agents | Test matrix |

## Template (every agent file)

| Section | Meaning |
|---|---|
| **Role** | What the agent is for, in one or two lines |
| **May** | Allowed actions, tools, and data sources |
| **Must not** | Forbidden actions |
| **Input checks** | What is validated before the agent acts |
| **Output checks** | What is validated before the result moves on |
| **On failure** | What happens when a check fails or a tool errors |
| **Enforced by** | Code, prompt, Bedrock Guardrail, or test |

## Principles

- `00_global.md` applies to every agent. Agent files do not repeat global rules.
- A rule that matters is enforced in **code** where possible. Prompts are the second line, not the only one.
- Every rule must have at least one enforcement point and, where possible, a test in `06_tests.md`.
- When code and these files disagree, fix one of them in the same change; the code and tests are what run.
