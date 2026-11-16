# AlphaForge web app (`apps/web/`)

Vite + React + TypeScript chat UI for the AlphaForge pipeline: persona picker, chat, live progress, and for
every answer the explanation built by the backend (recommended sectors, profile check, risk charts, market
context, claims, review, limitations, full run trace). English and Canadian French, switchable.

The backend owns the data shapes. This app reads them through the typed client in `packages/api-client`
(a pnpm workspace package, `"@alphaforge/api-client": "workspace:*"`), generated from `contracts/openapi.yaml`
and `contracts/asyncapi.yaml` (v0.2.0). To change a shape, edit the contract first, then run `pnpm client:build`.

## Run it

From the repo root (Python 3.11+, Node 20+, pnpm; `data/` must exist, see the root README):

```bash
# 1. Backend
source .venv/bin/activate
AGENT_MODE=demo uvicorn server.app:app --port 8000    # scripted boss/presenter (no LLM), real worker numbers
# or: uvicorn server.app:app --port 8000              # real agent on Bedrock (us-east-1, needs AWS creds)

# 2. Frontend
pnpm install
pnpm web:dev            # builds the client, then http://localhost:5173
```

`pnpm web:typecheck` runs `tsc --noEmit`; `pnpm web:build` runs it and then `vite build` (output in `dist/`, gitignored).

The dev server forwards `<base>api/*` (REST and WebSocket) to `http://localhost:8000`, so the browser only talks
to its own origin. Set `BACKEND_URL` to use another port, e.g. `BACKEND_URL=http://localhost:8001 pnpm web:dev`.

Behind the workshop's code-server proxy, create `apps/web/.env.local` with `VITE_BASE=/absproxy/5173/` and open
`https://<cloudfront-host>/absproxy/5173/`. Other settings are in `.env.example` (`VITE_API_BASE_URL` /
`VITE_WS_URL` for a deployed backend, `VITE_DEV_TOKEN`).

There is no mock server any more: `AGENT_MODE=demo` gives real numbers at no Bedrock cost, and every answer it
writes starts with "Demo mode". The app shows a banner when `GET /health` reports `agentMode: demo`.

## Auth

Sign-in is not wired yet. The backend runs in dev mode (any bearer token is accepted), and `src/api.ts` sends
`VITE_DEV_TOKEN` if set. The WebSocket uses a single-use ticket from `POST /ws-ticket` on every (re)connect.
Do not expose a dev-mode backend publicly.

## Routes

Relative to the Vite base: `/chat` persona picker, `/chat/amira|mateo|robert` chat. `/` and unknown paths
redirect to `/chat`. Each chat page creates a new conversation (conversations live in the server's memory).

## Files

| File | What it does |
|---|---|
| `src/main.tsx` | Mounts `<App/>` inside `LanguageProvider` |
| `src/App.tsx` | Routes |
| `src/api.ts` | REST client and `ChatSocket` factory (same-origin `<base>api` by default) |
| `src/health.ts` | `GET /health` once per page (demo banner) |
| `src/personas.ts` | Persona ids, names and ages for routing and headers before `GET /personas` answers |
| `src/PersonaPicker.tsx` | Cards with the translated description and the assumed limits from `GET /personas` |
| `src/AppBar.tsx` | Wordmark, Simple/Detailed switch (chat page), EN/FR switch, light/dark switch |
| `src/view.tsx` | Simple/Detailed mode (`localStorage.viewMode`): default of "Show full analysis" and "Show the evidence" |
| `src/registry/blocks/chat/` | Chat blocks from the chat-ui skill: `ChatContainer`, `ChatMessage` (user / assistant / system), `ChatInput` (Enter sends, Shift+Enter = new line, send turns into stop), `TypingIndicator`. Written locally: `ui.inference.sh/r/chat.json` returns 404 |
| `src/components/ui/button.ts`, `src/lib/utils.ts` | shadcn-style `buttonVariants` and `cn()` |
| `src/index.css` | Tailwind v4 (theme + utilities, no Preflight) around `styles.css`; shadcn token names (`bg-primary`, `text-muted-foreground`…) mapped to the noir palette, so both themes work |
| `src/Chat.tsx` | Conversation state, WebSocket events, branches (edit / regenerate), live stage line; renders with the chat blocks |
| `src/Answer.tsx` | Markdown answer (`react-markdown` + `remark-gfm`); claim tags become chips |
| `src/cite.ts` | Claim-tag parsing, same regexes as `server/explainer.py` (`TAG`, `STEP_NUMS`, `MAX_RANGE`) |
| `src/Explainer.tsx` | The `ExplainerPayload` panel: cards, charts, profile check, market, claims, review, limits, run |
| `src/Trace.tsx` | Every run-trace step, with input/output JSON; opens and scrolls to cited steps |
| `src/format.ts` | Percent, number and date formatting with `Intl` for `en-CA` / `fr-CA` |
| `src/i18n.tsx` | EN/FR dictionary and labels for every backend code |
| `src/styles.css` | Tokens (light/dark) and all styles |

## How an answer is shown

1. `message.start` adds the user message and an empty assistant message (`status: streaming`).
2. `generation.status` updates the stage line ("The workers are computing the numbers (7 steps)…"); stages are
   `queued, planning, analyzing, reviewing, writing, checking, done`.
3. `trace.step` events are upserted by `step.step` into `message.trace`, so the trace panel fills live.
4. `message.delta` events stream the answer as it is written (`reset: true` = start the text again; the demo
   agent sends one delta); `message.end` replaces the
   message with the final one, including `final` (the `ExplainerPayload`).

Claim tags written by the presenter are rendered as chips: `[fact: step 3, 7]` → "Fact · steps 3, 7",
`[fact: step 17-24]` → "steps 17–24", `[assumption]`, `[scenario]`. Clicking a fact chip (or a chart value, or a
"Fact · step N" chip in the panel) opens the trace and highlights those steps. Steps that are not in the trace
are dropped, as in the explainer.

**Summary first.** The presenter starts every answer with `## Summary` / `## Résumé` (at most 3 bullets).
`splitSummary` in `src/cite.ts` shows that summary and the recommended sector cards; the rest of the answer is
behind "Show full analysis", and everything below is behind "Show the evidence". The Simple / Detailed switch
sets the default of both toggles for every answer (Simple = closed); clicking a claim chip opens the evidence
and the trace. Answers without a summary are shown whole. At 1280 px and wider an answer uses two columns:
the text on the left, the evidence in a sticky panel on the right; narrower windows stack them.

The evidence:

- **Recommended sectors** and **What you asked about**: one card per `TargetSummary` (risk label, volatility,
  max drawdown, total return, 12-month momentum and trend, members, period and currency). Building blocks
  (bonds, broad market, gold, crypto) show the min–max range over their members, never a blended figure.
  The left border is the overall suitability status.
- **Conflicts noted by the boss agent**, when there are any.
- **Risk charts** from `riskTable`: annualized volatility against `personaLimits.vol_max`, and the 2022 worst
  fall against `personaLimits.stress_2022_max_drawdown`. Red = above the limit, green = within, navy = the
  persona has no limit of that kind. Bars are CSS, not a chart library.
- **Profile check**: one table per `SuitabilityResult`, every rule with its limit, value and status
  (conflict red, flag amber, pass green, info blue, N/A and not evaluated grey). The explanation under each
  rule is the suitability worker's text, in English.
- **Market context**, **Claims** (with their sources), **Quality review** (both reviewer verdicts, reasons,
  retries, "incomplete"), **Limitations and caveats**, and the run id with its S3 URI.
- **Trace**: every step (actor, action, summary, time), with the input and output JSON (cut at 6,000 characters).

Numbers from the backend are fractions (0.15 = 15%) and are formatted with one decimal, like the answer text
(`51.1%` in English, `51,1 %` in French). Rule codes, statuses, actors, sector names, phases, moods and caveats
are codes; `src/i18n.tsx` (`CODES`) translates them, and an unknown code is shown as sent.

## Connection drops

`ChatSocket` reconnects on its own (exponential backoff, new ticket each time). The server keeps running the
analysis while the socket is down, so a drop does not mark the answer as failed. When the socket is open again
the app reloads `GET /conversations/{id}/messages`, which has every trace step and the final answer if it
finished during the gap. Agent failures arrive as an `error` event (`agent_error`) followed by `message.end`
with `status: error`; `busy` and `invalid_message` errors only show a message.

## Language

The UI language follows the saved choice (`localStorage.lang`), else the browser language; the EN/FR button
switches it at once and sets `<html lang>` to `en-CA` or `fr-CA` (also before first paint, in `index.html`).
Every message is sent with `language`, and the backend writes that answer in that language. Earlier answers
stay in the language they were written in. Free text from the workers (rule explanations, warnings, the
"rule fired" sentence, sources) is in English and marked `lang="en"`.

French follows OQLF conventions, as on French-Canadian bank sites: guillemets with non-breaking spaces
(`« … »`), no space before `?` and `!`, a non-breaking space before `:` and `%`, the typographic apostrophe `’`,
and sentence case. Add every new string to both `EN` and `FR` in `src/i18n.tsx`; TypeScript fails the build if a
French key is missing.

## Look and colours

An original "noir" theme (no real brand's colours, fonts, logo or imagery), defined as CSS variables at the top of
`src/styles.css`. Dark is the default; the top-bar switch gives an off-white light version of the same system
(saved as `localStorage.colorTheme`). Noir: background `#0A0A0A` with a soft white glow behind the header, cards
`#1A1A1A` to `#141414` with a 1px `rgb(255 255 255 / 8%)` border and a light top edge, headings and numbers
`#FAFAFA`, body `#B5B5B5`, muted `#8A8A8A`. Primary buttons are white pills with black text; secondary buttons
are transparent with a light border. Colour only carries meaning: pass `#3FBF7F`, caution `#D9A441`, conflict
`#E0605A` (text `#E87570` on its tint), each on a 12% tint. Charts use grey bars, the persona limit as a dashed
white line, and amber for a bar above the limit. Every text/background pair meets WCAG AA (4.5:1). Headings use
Georgia where installed, else the bundled Source Serif 4 (with italics, e.g. "Who is *investing* today?"); body
text uses the bundled Inter (both SIL Open Font License, served by Vite, no font CDN). Numbers use tabular figures.
The logo is an original monochrome spark in an outlined rounded square.

- Status pills (`src/Status.tsx`): Pass (green check), Caution (amber, = `flag`), Conflict (red cross), Info, N/A,
  the same in cards, tables and the review.
- The summary is a hero card whose left border follows the answer: any conflict red, any caution amber, else green.
- While an answer streams: a 4-step progress line (Planning, Analysing, Reviewing, Writing), skeleton lines until
  the first text, then a blinking cursor at the end of the text.
- One-click questions: 3 per persona under the message bar (`sug.<persona>.<n>` in `src/i18n.tsx`).
- Claim chips are quiet grey outlines in Simple mode and coloured in Detailed mode.
- In the chat the assistant is called "Agent"; the header shows whose profile is checked ("Profile: Robert").
