# API contracts

| File | Describes |
|---|---|
| `openapi.yaml` | REST API (conversations, messages, `/me`, `/ws-ticket`) and **all shared schemas**, including the WebSocket payloads (`Ws*`). |
| `asyncapi.yaml` | WebSocket channel `/ws`: which messages the client and server send. Payloads reference `openapi.yaml`. |

Auth is Amazon Cognito (email + password). Clients send the Cognito ID token as `Authorization: Bearer <token>`.
Sign-up and sign-in go straight to Cognito, so they are not in this API.

## Commands (from the repo root, needs Node 20+ and pnpm)

```bash
pnpm install
pnpm contracts:lint     # Spectral lint of openapi.yaml
pnpm client:build       # regenerate types from openapi.yaml + typecheck + compile
pnpm client:test        # regenerate + run client tests
```

Generated file: `packages/api-client/src/generated/schema.ts`. Never edit it by hand; change the YAML and regenerate.

## Messages form a tree

Each message has a `parentId`. Editing a user message or regenerating a reply creates a **sibling**; nothing is overwritten.
`Conversation.activeLeafId` is the last message of the branch currently displayed.

## Agent interface (backend <-> agent module)

The backend calls one function. The agent module must not use Streamlit.

```python
def run_agent(persona_id: str, history: list[Message], user_text: str) -> Iterator[AgentEvent]
```

Events: `text_delta`, `tool_call` (name, arguments), `tool_result` (result, source, date range),
and a final `final` event carrying an `ExplainerPayload` (see `openapi.yaml`).
The backend maps these onto `message.delta`, `tool.call`, `tool.result` and `message.end`.
