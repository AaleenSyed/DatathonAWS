# Latency benchmark (real Bedrock, us-east-1, 2026-11-15)

Questions: the benchmark question (Amira, "Best industry for the quickest gains") and the 3 demo questions,
run in parallel, one process each (`python scripts/benchmark.py`). Times come from the run trace
(`trace.timing()`): boss turns / boss plan = model time of the boss's tool-calling turns and of its final plan;
tools = worker time; 1st text = when the first answer text exists (streamed since the change); total = whole run.
"plan" = reviewer verdicts, check_answer, Summary first, building block paired, and the demo expectations.

## BEFORE: boss Sonnet 5 with 9 fine tools and raw results, presenter Sonnet 5 (not streamed)

| BEFORE | boss turns | boss plan | tools | reviewer | presenter | 1st text | total | LLM calls | plan |
|---|---|---|---|---|---|---|---|---|---|
| amira: Best industry for the quickest gai | 11.1s | 17.9s | 0.9s | 0.0s | 13.6s | 43.5s | 43.6s | 4 | no Bonds / Broad market building block in ['Information Technology'] |
| robert: I want to put a big part of my sav | 20.9s | 11.9s | 0.9s | 0.0s | 13.7s | 47.5s | 47.6s | 5 | ok |
| amira: I only want AI and crypto, which i | 17.7s | 14.9s | 1.0s | 0.0s | 13.4s | 47.1s | 47.2s | 5 | no Bonds / Broad market building block in ['Information Technology', 'Crypto asset'] |
| mateo: Which industry gives balanced grow | 20.4s | 18.1s | 1.2s | 0.0s | 25.3s | 64.9s | 65.0s | 5 | ok |

## AFTER: boss Haiku 4.5 with coarse tools and compact results, presenter Sonnet 4.6 streamed; warm tool cache (server steady state)

| AFTER (warm) | boss turns | boss plan | tools | reviewer | presenter | 1st text | total | LLM calls | plan |
|---|---|---|---|---|---|---|---|---|---|
| amira: Best industry for the quickest gai | 1.0s | 1.9s | 0.0s | 0.0s | 10.2s | 3.7s | 13.2s | 3 | ok |
| robert: I want to put a big part of my sav | 1.3s | 2.4s | 0.3s | 0.0s | 12.6s | 4.8s | 16.7s | 3 | ok |
| amira: I only want AI and crypto, which i | 1.2s | 3.3s | 0.5s | 0.0s | 12.0s | 5.8s | 17.0s | 3 | ok |
| mateo: Which industry gives balanced grow | 1.0s | 3.0s | 0.0s | 0.0s | 12.0s | 4.7s | 16.0s | 3 | ok |

## AFTER, cold tool cache (first question within ~5 s of a server start, or no warm-up)

| AFTER (cold cache) | boss turns | boss plan | tools | reviewer | presenter | 1st text | total | LLM calls | plan |
|---|---|---|---|---|---|---|---|---|---|
| amira: Best industry for the quickest gai | 1.3s | 1.9s | 3.9s | 0.0s | 10.2s | 7.9s | 17.3s | 3 | ok |
| robert: I want to put a big part of my sav | 1.5s | 2.1s | 3.8s | 0.0s | 10.6s | 8.3s | 18.2s | 3 | ok |
| amira: I only want AI and crypto, which i | 1.5s | 2.3s | 3.9s | 0.0s | 12.6s | 8.6s | 20.5s | 3 | ok |
| mateo: Which industry gives balanced grow | 1.1s | 4.1s | 3.8s | 0.0s | 12.9s | 9.8s | 21.9s | 3 | ok |

## Boss model comparison (new design, presenter Sonnet 4.6, warm cache)

| warm boss claude-sonnet-5 | boss turns | boss plan | tools | reviewer | presenter | 1st text | total | LLM calls | plan |
|---|---|---|---|---|---|---|---|---|---|
| amira: Best industry for the quickest gai | 2.0s | 2.9s | 0.0s | 0.0s | 11.3s | 5.7s | 16.4s | 3 | ok |
| robert: I want to put a big part of my sav | 2.7s | 3.5s | 0.1s | 0.0s | 12.5s | 7.1s | 18.9s | 3 | ok |
| amira: I only want AI and crypto, which i | 2.9s | 5.8s | 0.6s | 0.0s | 11.3s | 10.2s | 20.7s | 3 | ok |
| mateo: Which industry gives balanced grow | 1.9s | 3.0s | 0.0s | 0.0s | 12.1s | 5.8s | 17.2s | 3 | ok |

| warm boss claude-sonnet-4-6 | boss turns | boss plan | tools | reviewer | presenter | 1st text | total | LLM calls | plan |
|---|---|---|---|---|---|---|---|---|---|
| amira: Best industry for the quickest gai | 1.0s | 2.3s | 0.0s | 0.0s | 15.0s | 6.3s | 18.4s | 3 | ok |
| robert: I want to put a big part of my sav | 1.3s | 2.9s | 0.2s | 0.0s | 11.8s | 5.2s | 16.3s | 3 | ok |
| amira: I only want AI and crypto, which i | 1.4s | 3.9s | 0.3s | 0.0s | 12.1s | 6.4s | 17.7s | 3 | ok |
| mateo: Which industry gives balanced grow | 1.0s | 2.3s | 0.0s | 0.0s | 12.1s | 4.2s | 15.6s | 3 | ok |

| warm boss claude-haiku-4-5 | boss turns | boss plan | tools | reviewer | presenter | 1st text | total | LLM calls | plan |
|---|---|---|---|---|---|---|---|---|---|
| amira: Best industry for the quickest gai | 1.0s | 1.9s | 0.0s | 0.0s | 11.8s | 3.8s | 14.8s | 3 | ok |
| robert: I want to put a big part of my sav | 1.3s | 2.4s | 0.2s | 0.0s | 11.0s | 4.6s | 14.9s | 3 | ok |
| amira: I only want AI and crypto, which i | 1.1s | 2.1s | 0.3s | 0.0s | 13.1s | 4.4s | 16.7s | 3 | ok |
| mateo: Which industry gives balanced grow | 0.9s | 1.7s | 0.0s | 0.0s | 12.5s | 3.4s | 15.3s | 3 | ok |

All three boss models produced a correct plan for all 4 questions; Haiku 4.5 is the
fastest, so it is the default (`BOSS_MODEL` overrides it). One run per question and model: expect a few
seconds of variation between runs.
