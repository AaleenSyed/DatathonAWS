# AlphaForge AI — PolyFinances Datathon 2026

*Version française : [one-pager.fr.md](one-pager.fr.md)*

**An agentic chatbot that explains its financial conclusions, with numbers and sources to back them.**

> Educational simulation for fictional personas. Not personalized financial advice. No real transactions.

## The problem
AI finance tools often give convincing but unverifiable answers: made-up numbers, no link to the investor's
profile, and an easy "yes" to a risky request.

## Our solution
The user picks the persona closest to them (or builds their own fictional profile in 7 questions), then asks
questions in plain language, in English or French:

| Persona | Profile | What the system must do |
|---|---|---|
| **Amira**, 26 | High risk, 15+ years | Tech/AI growth, but diversification enforced (crypto ≤ 15%) |
| **Mateo**, 41 | Moderate risk, 8–12 years | Balanced growth, ESG criteria, Energy flagged for review |
| **Robert**, 59 | Low–moderate risk, 3–5 years | Challenge "NVDA with a big part of my savings", with numbers |

Each answer recommends **a specific sector** (e.g. Consumer Staples + Bonds), with risk numbers, example
assets, how it fits the persona's horizon and risk tolerance, what could go wrong, and any profile conflicts.

## How it works
1. **Bedrock Guardrail** filters the question (personal advice to the real user, trades, PII, prompt injection).
2. **The intent router** (rules, then Claude Haiku 4.5) decides whether the message needs an analysis. Greetings,
   questions about the assistant, concept questions ("what does volatility mean?") and off-topic messages get a
   short, natural reply in about 1.5 s, with no numbers. Investing questions and follow-ups continue.
3. **The boss** (Claude Haiku 4.5 on Bedrock, a Strands agent) picks which tools to call and makes a plan.
4. **The workers** (deterministic Python, *no LLM*) compute everything: return, volatility, max drawdown,
   2022 stress test, business cycle (FRED), fit with the persona's limits.
5. **The reviewer** checks the work; on failure it sends the task back with reasons (max 2 retries).
6. **The presenter** (Claude Sonnet 4.6, streamed) writes the answer from the worker results only; every
   number must appear in the cited step.
7. **Output guardrail**, then the **full trace** is saved to Amazon S3.

## What sets us apart
- **The LLMs never compute.** Numbers come from tested code (535 tests); the AI reasons and explains.
- **Verifiable explainability.** Every claim is tagged `fact` (source + step), `assumption` or `scenario`,
  and opens the trace step that produced it.
- **It can say no.** A request that conflicts with the profile is challenged, with the limits in numbers.
- **It also just talks.** "Hi", "what can you help me with?" or "what is an ETF?" get a real reply, not a
  20-second report. Live test: 29/29 messages routed correctly (EN/FR), no investing question missed.
- **Fast.** Conversational reply in about 1.5 s; analysis: first text in 4–6 s, full answer in 13–17 s.

## AWS at the core
Amazon Bedrock (Converse + ConverseStream, Claude Haiku 4.5 and Sonnet 4.6) · Bedrock Guardrails
(ApplyGuardrail, input and output) · Amazon S3 (data and run traces).
Region `us-east-1`. Details: [architecture-aws.en.md](architecture-aws.en.md).

## Business value
For a bank, a broker or a financial-education platform: an assistant that **shows its reasoning**, respects
the client's profile and leaves a full audit trail — what advisors, compliance teams and regulators require.

**Limitations:** starter dataset 2021–2026 (survivorship bias), no external news or ESG data yet, persona
limits are team assumptions.
