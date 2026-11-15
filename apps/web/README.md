# AlphaForge frontend

Vite + React + TypeScript chat UI (persona picker, chat, trace and "why this answer" panels).

It uses the shared contract client from `../DatathonAWS/packages/api-client`
(`file:` dependency). Build that package first, and again after any change to `contracts/openapi.yaml`:

    cd ../DatathonAWS && pnpm install && pnpm client:build

Then, in this folder:

    pnpm install
    cp .env.example .env.local   # set API URL and a dev token
    pnpm dev

In this workshop, open the app at `https://<cloudfront-host>/absproxy/5173/` with
`VITE_BASE=/absproxy/5173/` in `.env.local`. The dev server forwards `<base>api/*` (REST and
WebSocket) to `http://localhost:8000`, so the browser never calls localhost directly.

Routes (after the base): `/chat` persona picker, `/chat/amira|mateo|robert` chat.
`/` and unknown paths redirect to `/chat`.

Sign-in (Cognito) is not wired yet; `VITE_DEV_TOKEN` is a placeholder.

## Language: Canadian French (fr-CA)

The interface is written in Canadian French. `index.html` declares `<html lang="fr-CA">`. There is no
i18n library and no language switch: the French strings are written directly in the components.

| File | What is translated |
|---|---|
| `src/PersonaPicker.tsx` | Step label, heading, intro, card prompt ("Commencer →"), disclaimer |
| `src/personas.ts` | Persona names ("26 ans") and descriptions |
| `src/Chat.tsx` | Top bar, connection status, empty state, message labels ("Vous", "Agent"), buttons, panels, error messages, screen-reader labels |
| `src/AppBar.tsx` | Theme switch label ("Passer au thème sombre / clair") |

Contract values stay in English in the data, and `src/Chat.tsx` shows a French label for each:

| Value | Label |
|---|---|
| Claim kind `fact` / `assumption` / `scenario` | Fait / Hypothèse / Scénario |
| Tool status `running` / `ok` / `error` | en cours / terminé / erreur |
| Tool `data_retriever` / `risk_analyst` / `suitability` / `market_context` | Collecte des données / Analyse du risque / Vérification de la convenance / Contexte de marché |

An unknown value is shown as is. Add a label to these maps when the backend adds a tool.

The real backend's answers, governance rules and error messages are shown as the backend sends them,
so they are French only if the backend writes them in French. Persona ids in the URL (`amira`,
`mateo`, `robert`) stay as they are because the API uses them.

### Mock server (fr-CA)

The mock server also answers in Canadian French:

- `mock-server/replies.mjs`: answer text, summary, claims, governance rules and notes, limitations,
  sector names, `source` and `risk_label` in tool results ("FICTIF" marks invented data). Numbers use
  French spacing (`27 %`, `-22 %`).
- `mock-server/server.mjs`: the default conversation title ("Nouvelle conversation") and every
  REST and WebSocket error `message`.

Not translated in the mock: error `code` values, tool names, enum values, JSON keys and field names
quoted in error messages (`conversationId`, `limit`…), because they belong to the contract. Console
logs stay in English.

Conventions used (OQLF style, as on French-Canadian bank sites):
- Guillemets with non-breaking spaces: `« Comment répartir mon portefeuille? »`.
- No space before `?` and `!`; a non-breaking space before `:` (`Limites : …`).
- Typographic apostrophe `’` (`l’Agent`, `aujourd’hui`).
- Sentence case for buttons and headings.

When you add UI text, write it in French with these conventions. If an English version is needed
later, move the strings into one file (for example `src/strings.ts`) or add a library such as
`react-intl`.

## Look and colours

Colours come from the bnc.ca palette and are defined as CSS variables at the top of
`src/styles.css` (light and dark theme; the theme follows the system and can be switched in the top
bar). Navy `#00314D` for text and buttons, red `#E41C23` for the logo mark, ice blue `#D9EEF4`
for the user's messages. In the chat the assistant is always called "Agent"; persona names appear
only on the picker.

## Mock backend

`mock-server/` is an in-memory stand-in for the real API. It follows
`../DatathonAWS/contracts/openapi.yaml` and `asyncapi.yaml` (REST, tickets, WebSocket streaming,
edit/regenerate branches, cancel). All answers and numbers are invented.

    pnpm mock          # http://localhost:8000 and ws://localhost:8000/ws

Optional: `MOCK_REQUIRE_AUTH=1` returns 401 without a Bearer token, `MOCK_DELAY_MS=60` sets the
streaming speed, `PORT=8000` sets the port. Stop it when the real backend is ready; the frontend
needs no changes.
