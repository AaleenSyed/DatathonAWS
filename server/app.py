"""FastAPI app: REST + WebSocket chat API (contracts/openapi.yaml, contracts/asyncapi.yaml) over the pipeline.

    uvicorn server.app:app --port 8000          # real agent (Bedrock)
    AGENT_MODE=demo uvicorn server.app:app      # scripted agent, real worker numbers, no LLM cost
"""
import asyncio
import contextlib
import functools
import json
import logging
import math
import threading
from typing import Literal

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from starlette.exceptions import HTTPException

from personas import PERSONAS, SOURCE as PERSONA_SOURCE
from server import agent, explainer
from server.auth import Authenticator, AuthError, TicketStore, bearer_token
from server.config import Settings, load_settings
from server.store import Store, public
from texts import lang_or_default

log = logging.getLogger("alphaforge.server")
Lang = Literal["en", "fr"]
PersonaKey = Literal["amira", "mateo", "robert"]
TEXT_MAX = 8000


# ---------- helpers ----------

def jsonsafe(obj):
    """JSON-compatible copy: NaN/inf -> None, tuples/sets -> lists, anything else unknown -> str."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): jsonsafe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonsafe(v) for v in obj]
    if isinstance(obj, set):
        return [jsonsafe(v) for v in sorted(obj, key=str)]
    return str(obj)


def to_trace_step(step: dict) -> dict:
    return jsonsafe({"step": step["step"], "actor": step["actor"], "action": step["action"],
                     "input": step.get("input"), "output": step.get("output"),
                     "outputSummary": step.get("output_summary", ""), "timestamp": step["timestamp"]})


def persona_out(key: str) -> dict:
    p = PERSONAS[key]
    return {"id": key, "name": p["name"], "age": p["age"], "occupation": p["occupation"],
            "riskTolerance": p["risk_tolerance"], "horizonYears": p["horizon_years"], "goal": p["goal"],
            "preferences": list(p["preferences"]), "limits": p["limits"],
            "esgReviewTickers": list(p["esg_review_tickers"]), "source": PERSONA_SOURCE}


def api_error(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


# ---------- request bodies ----------

class CreateConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    personaId: PersonaKey
    title: str | None = Field(default=None, min_length=1, max_length=120)
    language: Lang | None = None


class UpdateConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=120)
    activeLeafId: str | None = None
    language: Lang | None = None


class WsSend(BaseModel):
    type: Literal["message.send"]
    requestId: str | None = None
    conversationId: str
    parentId: str | None = None
    text: str = Field(min_length=1, max_length=TEXT_MAX)
    language: Lang | None = None


class WsEdit(BaseModel):
    type: Literal["message.edit"]
    requestId: str | None = None
    conversationId: str
    messageId: str
    text: str = Field(min_length=1, max_length=TEXT_MAX)
    language: Lang | None = None


class WsRegenerate(BaseModel):
    type: Literal["message.regenerate"]
    requestId: str | None = None
    conversationId: str
    messageId: str
    language: Lang | None = None


class WsCancel(BaseModel):
    type: Literal["generation.cancel"]
    conversationId: str


class WsPing(BaseModel):
    type: Literal["ping"]


CLIENT_MESSAGE = TypeAdapter(WsSend | WsEdit | WsRegenerate | WsCancel | WsPing)


# ---------- WebSocket fan-out ----------

class Hub:
    """Open sockets per user. Each socket has an outbox queue and one writer task, so events keep their order."""

    def __init__(self):
        self.sockets: dict[str, dict[WebSocket, asyncio.Queue]] = {}

    def add(self, user_id: str, ws: WebSocket) -> asyncio.Task:
        q: asyncio.Queue = asyncio.Queue()
        self.sockets.setdefault(user_id, {})[ws] = q
        return asyncio.create_task(self._writer(user_id, ws, q))

    def remove(self, user_id: str, ws: WebSocket):
        q = self.sockets.get(user_id, {}).pop(ws, None)
        if q is not None:
            q.put_nowait(None)  # stops the writer
        if user_id in self.sockets and not self.sockets[user_id]:
            del self.sockets[user_id]

    async def _writer(self, user_id, ws, q):
        while (payload := await q.get()) is not None:
            try:
                await ws.send_text(payload)
            except Exception:
                self.remove(user_id, ws)
                return

    def to_socket(self, user_id: str, ws: WebSocket, event: dict):
        q = self.sockets.get(user_id, {}).get(ws)
        if q is not None:
            q.put_nowait(json.dumps(jsonsafe(event), ensure_ascii=False))

    def to_user(self, user_id: str, event: dict):
        payload = json.dumps(jsonsafe(event), ensure_ascii=False)
        for q in list(self.sockets.get(user_id, {}).values()):
            q.put_nowait(payload)


class Generation:
    def __init__(self, user_id: str, conv_id: str, assistant: dict):
        self.user_id, self.conv_id, self.assistant = user_id, conv_id, assistant
        self.cancelled = False
        self.stage = None
        self.task: asyncio.Task | None = None


# ---------- app ----------

def create_app(settings: Settings | None = None, runner=None, authenticator: Authenticator | None = None) -> FastAPI:
    """runner(persona, question, history, lang, on_step, session_id) -> ChatSession.ask() result.
    Defaults to server.agent.run_turn in the configured AGENT_MODE. Tests inject a fast runner."""
    settings = settings or load_settings()
    auth = authenticator or Authenticator(settings)
    tickets = TicketStore(settings.ticket_ttl_seconds)
    store, hub = Store(), Hub()
    running: dict[str, Generation] = {}
    run = runner or (lambda persona, question, history, lang, on_step, session_id, on_delta=None: agent.run_turn(
        persona, question, history, lang, on_step, mode=settings.agent_mode, session_id=session_id,
        on_delta=on_delta))
    streams = agent.accepts_delta(run)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        if settings.warm_up:  # fill the tool cache so the first question is fast (background, ~5 s)
            threading.Thread(target=agent.warm_up, daemon=True, name="warm-up").start()
        yield

    app = FastAPI(title="AlphaForge AI Chat API", version="0.2.1", lifespan=lifespan)
    app.state.store, app.state.running, app.state.tickets = store, running, tickets
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                       allow_headers=["*"], allow_credentials=False)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {
            "code": {404: "not_found", 401: "unauthorized", 405: "invalid_request"}.get(exc.status_code, "error"),
            "message": str(exc.detail)}
        return JSONResponse(detail, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:]) or 'body'}: {e['msg']}" for e in exc.errors())
        return JSONResponse({"code": "invalid_request", "message": msg or "invalid request"}, status_code=400)

    def user_of(request: Request) -> dict:
        try:
            return auth.user_from_token(bearer_token(request.headers.get("authorization")))
        except AuthError as e:
            api_error(401, "unauthorized", str(e))

    def conversation_of(user: dict, conv_id: str) -> dict:
        conv = store.get_conversation(user["id"], conv_id)
        if conv is None:
            api_error(404, "not_found", "conversation not found")
        return conv

    # ----- REST -----

    @app.get("/health")
    async def health():
        return {"status": "ok", "agentMode": "demo" if settings.agent_mode == "demo" else "bedrock",
                "authMode": settings.auth_mode}

    @app.get("/me")
    async def me(request: Request):
        return user_of(request)

    @app.post("/ws-ticket")
    async def ws_ticket(request: Request):
        return tickets.issue(user_of(request))

    @app.get("/personas")
    async def personas(request: Request):
        user_of(request)
        return {"items": [persona_out(k) for k in PERSONAS]}

    @app.get("/conversations")
    async def list_conversations(request: Request, limit: int = Query(25, ge=1, le=100), cursor: str | None = None):
        user = user_of(request)
        try:
            start = int(cursor) if cursor is not None else 0
            assert start >= 0
        except (ValueError, AssertionError):
            api_error(400, "invalid_request", "invalid cursor")
        items = store.list_conversations(user["id"])
        page = items[start:start + limit]
        nxt = str(start + limit) if start + limit < len(items) else None
        return {"items": [public(c) for c in page], "nextCursor": nxt}

    @app.post("/conversations", status_code=201)
    async def create_conversation(request: Request, body: CreateConversation):
        user = user_of(request)
        conv = store.create_conversation(user["id"], body.personaId, body.title, body.language or "en")
        return public(conv)

    @app.get("/conversations/{conversation_id}")
    async def get_conversation(request: Request, conversation_id: str):
        return public(conversation_of(user_of(request), conversation_id))

    @app.patch("/conversations/{conversation_id}")
    async def update_conversation(request: Request, conversation_id: str, body: UpdateConversation):
        conv = conversation_of(user_of(request), conversation_id)
        fields = body.model_fields_set
        if not fields:
            api_error(400, "invalid_request", "nothing to update")
        if "activeLeafId" in fields:
            if body.activeLeafId is None or store.get_message(conv["id"], body.activeLeafId) is None:
                api_error(400, "invalid_request", "activeLeafId is not a message of this conversation")
            conv["activeLeafId"] = body.activeLeafId
        if "title" in fields:
            if body.title is None:
                api_error(400, "invalid_request", "title cannot be null")
            conv["title"], conv["_titled"] = body.title, True
        if "language" in fields:
            if body.language is None:
                api_error(400, "invalid_request", "language cannot be null")
            conv["language"] = body.language
        store.touch(conv)
        return public(conv)

    @app.delete("/conversations/{conversation_id}", status_code=204)
    async def delete_conversation(request: Request, conversation_id: str):
        user = user_of(request)
        conversation_of(user, conversation_id)
        gen = running.pop(conversation_id, None)
        if gen:
            gen.cancelled = True
        store.delete_conversation(user["id"], conversation_id)
        return Response(status_code=204)

    @app.get("/conversations/{conversation_id}/messages")
    async def list_messages(request: Request, conversation_id: str):
        conv = conversation_of(user_of(request), conversation_id)
        return {"items": [public(m) for m in store.list_messages(conv["id"])]}

    # ----- WebSocket -----

    def ws_error(user_id, ws, code, message, request_id=None, conv_id=None):
        event = {"type": "error", "code": code, "message": message}
        if request_id:
            event["requestId"] = request_id
        if conv_id:
            event["conversationId"] = conv_id
        hub.to_socket(user_id, ws, event)

    def set_stage(gen: Generation, stage: str | None):
        if stage and stage != gen.stage:
            gen.stage = stage
            hub.to_user(gen.user_id, {"type": "generation.status", "conversationId": gen.conv_id,
                                      "messageId": gen.assistant["id"], "stage": stage,
                                      "steps": len(gen.assistant["trace"])})

    def end_message(gen: Generation):
        hub.to_user(gen.user_id, {"type": "message.end", "conversationId": gen.conv_id,
                                  "message": public(gen.assistant)})

    async def run_generation(gen: Generation, conv: dict, user_msg: dict, lang: str):
        loop = asyncio.get_running_loop()
        history = store.history_before(conv["id"], user_msg)

        def on_step_loop(step):
            if gen.cancelled:
                return
            ts = to_trace_step(step)
            gen.assistant["trace"].append(ts)
            hub.to_user(gen.user_id, {"type": "trace.step", "conversationId": gen.conv_id,
                                      "messageId": gen.assistant["id"], "step": ts})
            set_stage(gen, agent.stage_for(step))

        def on_step(step):  # called from the pipeline thread
            loop.call_soon_threadsafe(on_step_loop, step)

        shown = []  # text already sent as message.delta (streamed answer)

        def on_delta_loop(chunk, reset):
            if gen.cancelled:
                return
            if reset:
                shown.clear()
            shown.append(chunk)
            gen.assistant["content"] = "".join(shown)
            event = {"type": "message.delta", "conversationId": gen.conv_id, "messageId": gen.assistant["id"],
                     "delta": chunk}
            if reset:
                event["reset"] = True
            hub.to_user(gen.user_id, event)
            set_stage(gen, "writing")

        def on_delta(chunk, reset=False):  # called from the pipeline thread
            loop.call_soon_threadsafe(on_delta_loop, chunk, reset)

        set_stage(gen, "queued" if agent.RUN_LOCK.locked() else "planning")
        try:
            extra = {"on_delta": on_delta} if streams else {}
            result = await loop.run_in_executor(None, functools.partial(
                run, conv["personaId"], user_msg["content"], history, lang, on_step, conv["id"][:8], **extra))
        except Exception as e:
            log.exception("generation failed")
            if gen.cancelled:
                return
            gen.assistant["status"] = "error"
            hub.to_user(gen.user_id, {"type": "error", "conversationId": gen.conv_id, "code": "agent_error",
                                      "message": f"the analysis failed: {str(e)[:300]}"})
            end_message(gen)
            return
        finally:
            if running.get(gen.conv_id) is gen:
                del running[gen.conv_id]
        if gen.cancelled:
            return
        try:
            final = explainer.build(result, conv["personaId"], lang)
        except Exception:
            log.exception("explainer failed")
            final = None
        gen.assistant.update(content=result["answer"], status="complete", final=jsonsafe(final),
                             trace=[to_trace_step(s) for s in result["trace"].steps])
        if conv["id"] in store.conversations:
            store.touch(conv)
        await asyncio.sleep(0)  # deliver deltas still queued from the pipeline thread first
        streamed = "".join(shown)
        if streamed != result["answer"]:
            # Not streamed (demo agent), or the pipeline added text (disclaimer, notes): send the final text.
            # A streamed prefix only needs the rest; anything else replaces what was shown.
            if streamed and result["answer"].startswith(streamed):
                event = {"delta": result["answer"][len(streamed):]}
            else:
                event = {"delta": result["answer"], **({"reset": True} if streamed else {})}
            hub.to_user(gen.user_id, {"type": "message.delta", "conversationId": gen.conv_id,
                                      "messageId": gen.assistant["id"], **event})
        set_stage(gen, "done")
        end_message(gen)

    def start_generation(user: dict, conv: dict, user_msg: dict, request_id, lang: str, new_user_msg: bool):
        assistant = store.add_message(conv, "assistant", user_msg["id"], "", "streaming", lang)
        conv["activeLeafId"] = assistant["id"]
        store.auto_title(conv, user_msg["content"])
        start = {"type": "message.start", "conversationId": conv["id"], "message": public(assistant)}
        if request_id:
            start["requestId"] = request_id
        if new_user_msg:
            start["userMessage"] = public(user_msg)
        hub.to_user(user["id"], start)
        gen = Generation(user["id"], conv["id"], assistant)
        running[conv["id"]] = gen
        gen.task = asyncio.create_task(run_generation(gen, conv, user_msg, lang))

    async def handle(ws: WebSocket, user: dict, raw: str):
        uid = user["id"]
        try:
            msg = CLIENT_MESSAGE.validate_python(json.loads(raw))
        except (ValueError, ValidationError) as e:
            first = e.errors()[0]["msg"] if isinstance(e, ValidationError) else "not JSON"
            return ws_error(uid, ws, "invalid_message", f"invalid message: {first}")
        if isinstance(msg, WsPing):
            return hub.to_socket(uid, ws, {"type": "pong"})
        rid = getattr(msg, "requestId", None)
        conv = store.get_conversation(uid, msg.conversationId)
        if conv is None:
            return ws_error(uid, ws, "not_found", "conversation not found", rid, msg.conversationId)
        if isinstance(msg, WsCancel):
            gen = running.pop(conv["id"], None)
            if gen is None:
                return ws_error(uid, ws, "not_running", "no generation is running", conv_id=conv["id"])
            gen.cancelled = True
            gen.assistant["status"] = "cancelled"
            return end_message(gen)
        if conv["id"] in running:
            return ws_error(uid, ws, "busy", "a reply is already being written for this conversation", rid, conv["id"])
        lang = lang_or_default(msg.language or conv["language"])

        if isinstance(msg, WsSend):
            text = msg.text.strip()
            if not text:
                return ws_error(uid, ws, "invalid_message", "text is empty", rid, conv["id"])
            parent_id = msg.parentId if "parentId" in msg.model_fields_set else conv["activeLeafId"]
            if parent_id is not None:
                parent = store.get_message(conv["id"], parent_id)
                if parent is None or parent["role"] != "assistant":
                    return ws_error(uid, ws, "invalid_message", "parentId must be an assistant message of this "
                                    "conversation", rid, conv["id"])
            user_msg = store.add_message(conv, "user", parent_id, text, "complete", lang)
            return start_generation(user, conv, user_msg, rid, lang, new_user_msg=True)

        if isinstance(msg, WsEdit):
            old = store.get_message(conv["id"], msg.messageId)
            text = msg.text.strip()
            if old is None or old["role"] != "user":
                return ws_error(uid, ws, "invalid_message", "messageId must be a user message", rid, conv["id"])
            if not text:
                return ws_error(uid, ws, "invalid_message", "text is empty", rid, conv["id"])
            user_msg = store.add_message(conv, "user", old["parentId"], text, "complete", lang)
            return start_generation(user, conv, user_msg, rid, lang, new_user_msg=True)

        if isinstance(msg, WsRegenerate):
            old = store.get_message(conv["id"], msg.messageId)
            if old is None or old["role"] != "assistant":
                return ws_error(uid, ws, "invalid_message", "messageId must be an assistant message", rid, conv["id"])
            user_msg = store.get_message(conv["id"], old["parentId"])
            return start_generation(user, conv, user_msg, rid, lang, new_user_msg=False)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        try:
            user = tickets.redeem(ws.query_params.get("ticket"))
        except AuthError:
            await ws.close(code=4401, reason="invalid ticket")
            return
        writer = hub.add(user["id"], ws)
        try:
            while True:
                await handle(ws, user, await ws.receive_text())
        except WebSocketDisconnect:
            pass
        finally:
            hub.remove(user["id"], ws)
            await asyncio.gather(writer, return_exceptions=True)

    return app


app = create_app()
