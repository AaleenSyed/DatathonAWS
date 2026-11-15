# Handoff: web backend + React frontend (Nov 15, 2026)

Branch **`web-app`** (pushed to GitHub). **Not merged into `main`** yet. The backend is done and tested, and
the React app now uses contract v0.2 (to-do items 1 to 4 below are done: it compiles, builds, and was
smoke-tested in demo mode in EN and FR). `main` = 41f03fe (phase 3 merged, 188 tests).

## Read this first: data is not on GitHub
`data/*.csv` is gitignored (team rule). To work at home you need `data/` (starter CSVs + `macro_extra.csv`).
The S3 copy (`DATA_BUCKET` in `.env`) is **deleted with the AWS account on Monday Nov 16, 13:59**. Download
`data/` from the workshop machine or S3 before then. `.env` is also not on GitHub (never commit it).
Without AWS credentials, use `AGENT_MODE=demo` (no Bedrock; real worker numbers).

## Decisions taken
- **The backend owns the data shapes.** The frontend adapts to what the pipeline produces. To change a shape,
  edit `contracts/openapi.yaml`, then run `pnpm client:build` to regenerate the TypeScript client.
- **React (`apps/web/`), not Streamlit.** `CLAUDE.md` and `.kiro/steering/project.md` are updated.
- **English + Canadian French**, switchable in the UI; the answer is written in the language of each message.
- Contract bumped to **v0.2.0** (`contracts/openapi.yaml`, `contracts/asyncapi.yaml`):
  - `Message.toolCalls` → `Message.trace` (every run-trace step: user, boss, workers, reviewer, presenter).
  - WS `tool.call` / `tool.result` → `trace.step` (live) + `generation.status` (stage: queued, planning,
    analyzing, reviewing, writing, checking, done).
  - `ExplainerPayload` rebuilt from our data: `recommendedSectors`, `requestedTargets`, `conflicts`,
    `suitability` (all 6 statuses: conflict, flag, info, pass, not_applicable, not_evaluated), `riskTable`
    (chart rows), `personaLimits`, `marketContext`, `claims` (parsed from the `[fact: step N]` tags), `review`
    (reviewer verdicts + retries), `limitations`, `caveats` (codes the UI translates), `run` (run id, S3 URI).
    The old `summary` / `governance` fields are gone (`governance` showed a conflict as a green ✓).
  - New: `GET /health`, `GET /personas`, `language` on conversations and WS messages.
  - Numbers are **fractions** (0.15 = 15%). Rule codes, statuses, actors and sector names are codes the UI translates.

## Done and tested
| Part | Files | Status |
|---|---|---|
| Web backend | `server/app.py` (REST + WebSocket), `store.py` (conversations, message tree), `auth.py` (Cognito ID tokens or dev mode, single-use 30 s WS tickets), `agent.py` (runs the pipeline, stages), `explainer.py` (builds `ExplainerPayload` from the trace, no LLM), `demo_agent.py` (scripted boss/presenter, EN/FR), `config.py` | Done |
| Pipeline additions (backward compatible) | `pipeline.py`: `ChatSession(history=, lang=, on_step=)`; boss seeded with the branch history, so edit/regenerate work. `run_trace.py`: live step listener. `presenter.py` + `prompts/lang_en.txt`, `prompts/lang_fr.txt`: answer language. `reviewer.py`: French numbers (51,1 %) are checked; sentence split handles À/É. `texts.py`: disclaimers and notes in EN/FR | Done |
| Contract + client | `contracts/*.yaml`, `packages/api-client/src/types.ts`, regenerated `generated/schema.ts` | Spectral lint: no errors. Client build + 8 client tests pass |
| Tests | `tests/test_server.py` (22), `tests/test_explainer.py` (11), `tests/contract.py` (checks every REST response and WS event against `openapi.yaml`), `tests/test_live_server.py` (2, needs `RUN_LIVE=1`) | **221 passed**. Live on Bedrock: 2 passed (Robert/NVDA in French: work + answer checks passed, trace saved to S3; Amira follow-up in English used the history) |
| Frontend on contract v0.2 | `apps/web/`: `Chat.tsx` (WS events `trace.step` / `generation.status`, live stage line, reload after reconnect, `language` on every send), `Answer.tsx` + `cite.ts` (markdown, claim chips that open the trace), `Explainer.tsx` (cards, risk charts, profile check, market, claims, review, limits, run), `Trace.tsx`, `format.ts`, `health.ts` (demo banner). See `apps/web/README.md` | Done. `pnpm web:build` passes; headless-browser smoke test below |
| i18n | `apps/web/src/i18n.tsx` wired in: `LanguageProvider` in `main.tsx`, EN/FR button in `AppBar.tsx`, `PersonaPicker.tsx` reads `GET /personas` (assumed limits), `<html lang>` set before first paint and on switch | Done |
| Tools | `scripts/inspect_target.py` (readable .txt report), `scripts/sanity_check.py` (31 independent checks; all pass) | Done |

## Frontend smoke test (demo mode, headless Chromium)
Backend `AGENT_MODE=demo` + `pnpm web:dev`; each demo question sent from the empty-state suggestion button.
| Check | Result |
|---|---|
| Robert EN, NVDA question | NVDA card "Conflict"; vol chart 7 bars vs 10.0% limit (4 above); 2022 chart vs -15.0%; profile table shows conflict / flag / info / N/A / pass |
| Mateo FR | All labels in French (« Services publics », « Signalement »), numbers `14,7 %`; Energy flagged for ESG review; follow-up question + Régénérer → branch switcher 2/2 |
| Amira EN | Crypto building block shown as BTC-USD/ETH-USD range; "No limit of this kind for Amira" on both charts (she has no vol or 2022 limit) |
| Claim chip | Opens the trace and highlights the cited step |
| Socket dropped mid-run | Reconnects, reloads the messages, shows the finished answer; no "Interrupted" tag |
| EN/FR button, dark theme | Switch at once; `<html lang>` follows; no console errors in any run |
| `pytest` / client tests | 221 passed, 5 skipped / 8 passed |
Not tested: a real Bedrock run through the UI, and the workshop proxy URL (`VITE_BASE=/absproxy/5173/`).

## To do, in order
1. **Merge `web-app` → `main`** via PR. Tell the frontend teammate to work in `apps/web/` from now on
   (`/workshop/frontend` is the old copy; its mock server and Vite were still running on ports 8000 and 5173).
2. Before the video: one real Bedrock question through the UI (`uvicorn server.app:app`, no `AGENT_MODE`).
3. Remaining phases: 4 guardrail, 5 news/ethics (optional), 7 docs (README sources/licenses, technical doc,
   one-pager, 5-min video). Repo + README due **Sunday Nov 15, 23:59**.

## Known issues (from the reviews; not blocking)
- Presenter once wrote that XBB.TO is "within" Robert's 2022 limit (-15.3% vs -15.0%). The number check cannot catch misreadings.
- Dates in the trace (2021-11-12) make the numbers 11 and 12 look "supported" in the answer check.
- Annualized return differs for the same asset alone vs inside a basket (NVDA 44.4% vs 45.6%): years = returns/252 on common dates.
- Mateo's "Utilities" is one company (FTS.TO).
- The 2022 chart only has bars for targets the boss ran `stress_test_2022` on (`riskTable.stress2022*` comes from
  those steps). In demo mode that is only the requested target, so Robert's chart shows NVDA alone, while the
  profile table shows Consumer Staples' 2022 drawdown (-13.7%) from the suitability step.
- Server: conversations are in memory (lost on restart; traces stay in `runs/` and S3). One run at a time
  (`agent_tools.CONTEXT` is global; others show "queued"). Cancel discards the result but the run finishes in
  the background. The Bedrock presenter streams its text as many `message.delta` events (`reset: true` replaces a rejected draft); the demo agent sends one.
- Auth: Cognito verification is implemented and tested, but no user pool exists and the frontend has no
  sign-in yet, so the server runs in **dev mode** (any token). Do not expose it publicly in dev mode.

## How to run
```bash
# Python (3.11+), from the repo root
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python -m pytest -q                                   # 221 tests (needs data/)
RUN_LIVE=1 python -m pytest -q -s tests/test_live_server.py   # Bedrock, costs money, needs AWS creds

# Backend
AGENT_MODE=demo uvicorn server.app:app --port 8000    # no LLM, real numbers
uvicorn server.app:app --port 8000                    # real agent (Bedrock, us-east-1)
curl localhost:8000/health

# Frontend (Node 20+, pnpm), from the repo root
pnpm install
pnpm client:build && pnpm client:test
pnpm web:dev            # http://localhost:5173 ; /api/* is proxied to :8000
# behind the workshop proxy: apps/web/.env.local -> VITE_BASE=/absproxy/5173/
```
