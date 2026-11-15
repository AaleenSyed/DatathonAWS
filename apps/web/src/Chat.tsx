import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  GenerationStage,
  Message,
  PersonaId,
  SocketStatus,
  TraceStep,
  WsClientMessage,
  WsServerMessage,
} from "@alphaforge/api-client";
import { api, createChatSocket } from "./api";
import { Answer } from "./Answer";
import { AppBar } from "./AppBar";
import { Explainer } from "./Explainer";
import { useHealth } from "./health";
import { useI18n, type Key } from "./i18n";
import { personaById } from "./personas";
import { Trace } from "./Trace";

interface Progress {
  stage: GenerationStage;
  steps: number;
}

interface TraceView {
  open: boolean;
  highlight: number[];
  focus: number;
}

interface ErrorState {
  key: Key;
  vars?: Record<string, string>;
  detail?: string;
}

const CLOSED_TRACE: TraceView = { open: false, highlight: [], focus: 0 };

export function Chat({ personaId, onBack }: { personaId: PersonaId; onBack: () => void }) {
  const { t, lang, code } = useI18n();
  const health = useHealth();
  const persona = personaById(personaId);
  const name = persona?.name ?? personaId;

  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]); // every branch
  const [activeLeafId, setActiveLeafId] = useState<string | null>(null);
  const [progress, setProgress] = useState<Record<string, Progress>>({});
  const [traceView, setTraceView] = useState<Record<string, TraceView>>({});
  const [status, setStatus] = useState<SocketStatus>("idle");
  const [error, setError] = useState<ErrorState | null>(null);
  const [text, setText] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const socket = useRef(createChatSocket());
  const pendingScroll = useRef<{ id: string; block: ScrollLogicalPosition } | null>(null);
  const lostConnection = useRef(false);
  const langRef = useRef(lang);
  langRef.current = lang;

  useEffect(() => {
    const s = socket.current;
    const offStatus = s.onStatus(setStatus);
    const offMsg = s.onMessage((m) => {
      setMessages((prev) => reduce(prev, m));
      switch (m.type) {
        case "message.start":
          setActiveLeafId(m.message.id);
          pendingScroll.current = { id: m.message.id, block: "end" };
          break;
        case "generation.status":
          setProgress((p) => ({ ...p, [m.messageId]: { stage: m.stage, steps: m.steps } }));
          pendingScroll.current = { id: m.messageId, block: "end" };
          break;
        case "message.end":
          // Show the start of the answer, not the bottom of the explanation panel.
          pendingScroll.current = { id: m.message.id, block: "start" };
          break;
        case "error":
          // agent_error is followed by message.end (status error); busy / invalid_message change nothing.
          setError({ key: "chat.errServer", vars: { code: m.code }, detail: m.message });
          break;
      }
    });
    (async () => {
      const { data, error: err } = await api.POST("/conversations", {
        body: { personaId, language: langRef.current },
      });
      if (err || !data) return setError({ key: "chat.errCreate" });
      setConversationId(data.id);
      await s.connect();
    })().catch((e) => setError({ key: "chat.errCreate", detail: String(e) }));
    return () => {
      offStatus();
      offMsg();
      s.close();
    };
  }, [personaId]);

  // The server keeps running while the socket is down. When it is back, reload the messages instead of
  // marking the answer as failed (events sent during the gap are lost).
  useEffect(() => {
    if (status === "reconnecting") lostConnection.current = true;
    if (status !== "open" || !lostConnection.current || !conversationId) return;
    lostConnection.current = false;
    void api
      .GET("/conversations/{conversationId}/messages", { params: { path: { conversationId } } })
      .then(({ data, error: err }) => {
        if (err || !data) return setError({ key: "chat.errLoad" });
        setMessages(data.items);
      });
  }, [status, conversationId]);

  const path = useMemo(() => activePath(messages, activeLeafId), [messages, activeLeafId]);
  const generating = messages.some((m) => m.status === "streaming");
  const canAct = status === "open" && !!conversationId && !generating;

  useEffect(() => {
    const p = pendingScroll.current;
    if (!p) return;
    pendingScroll.current = null;
    document.getElementById(`msg-${p.id}`)?.scrollIntoView({ block: p.block, behavior: "smooth" });
  }, [messages, progress]);

  // One stable callback per message, so memoized answers do not re-render while typing.
  const citeFns = useRef(new Map<string, (steps: number[]) => void>());
  const citeFor = useCallback((id: string) => {
    let fn = citeFns.current.get(id);
    if (!fn) {
      fn = (steps: number[]) =>
        setTraceView((v) => ({ ...v, [id]: { open: true, highlight: steps, focus: (v[id]?.focus ?? 0) + 1 } }));
      citeFns.current.set(id, fn);
    }
    return fn;
  }, []);

  function send(message: WsClientMessage): boolean {
    try {
      socket.current.send(message);
      setError(null);
      return true;
    } catch {
      setError({ key: "chat.errSend" });
      return false;
    }
  }

  function sendMessage(value = text.trim()) {
    if (!value || !canAct) return;
    if (send({ type: "message.send", conversationId: conversationId!, text: value, language: lang })) setText("");
  }

  function saveEdit(messageId: string) {
    const value = editText.trim();
    if (!value || !canAct) return;
    if (send({ type: "message.edit", conversationId: conversationId!, messageId, text: value, language: lang })) {
      setEditingId(null);
    }
  }

  function regenerate(messageId: string) {
    if (canAct) send({ type: "message.regenerate", conversationId: conversationId!, messageId, language: lang });
  }

  function cancel() {
    if (conversationId) send({ type: "generation.cancel", conversationId });
  }

  async function switchBranch(sibling: Message) {
    if (generating || !conversationId) return;
    const leaf = latestLeaf(messages, sibling);
    setActiveLeafId(leaf.id);
    const { error: err } = await api.PATCH("/conversations/{conversationId}", {
      params: { path: { conversationId } },
      body: { activeLeafId: leaf.id },
    });
    if (err) setError({ key: "chat.errBranch" });
  }

  const example = t(`chat.ex.${personaId}` as Key);

  return (
    <div className="page chat-page">
      <AppBar
        left={
          <>
            <button className="back" onClick={onBack}>
              <span aria-hidden="true">←</span> {t("chat.back")}
            </button>
            <span className="persona-name">{t("chat.profile", { name })}</span>
          </>
        }
        right={
          <span className={`status status-${status}`} role="status">
            <span className="dot" aria-hidden="true" />
            <span className="status-text">{t(`status.${status}` as Key)}</span>
          </span>
        }
      />
      {health?.agentMode === "demo" && <p className="banner">{t("app.demo")}</p>}
      <main className="chat">
        <section className="messages" aria-live="polite">
          {path.length === 0 && (
            <div className="empty">
              <h2>{t("chat.emptyTitle")}</h2>
              <p>{t("chat.emptyHint", { name })}</p>
              <p className="try">
                <span className="muted">
                  {t("chat.try")}
                  {t("colon")}
                </span>
                <button type="button" className="suggestion" disabled={!canAct} onClick={() => sendMessage(example)}>
                  {t("chat.quoted", { q: example })}
                </button>
              </p>
            </div>
          )}
          {path.map((m) => {
            const siblings = siblingsOf(messages, m);
            const index = siblings.findIndex((s) => s.id === m.id);
            const view = traceView[m.id] ?? CLOSED_TRACE;
            const prog = progress[m.id];
            return (
              <article key={m.id} id={`msg-${m.id}`} className={`msg ${m.role}${m.final ? " has-final" : ""}`}>
                <div className="msg-head">
                  <span className="msg-role">{m.role === "user" ? t("chat.you") : t("chat.agent")}</span>
                  {siblings.length > 1 && (
                    <span className="branches" aria-label={t("chat.versions")}>
                      <button
                        aria-label={t("chat.prev")}
                        disabled={generating || index === 0}
                        onClick={() => switchBranch(siblings[index - 1])}
                      >
                        ‹
                      </button>
                      <span>
                        {index + 1}/{siblings.length}
                      </span>
                      <button
                        aria-label={t("chat.next")}
                        disabled={generating || index === siblings.length - 1}
                        onClick={() => switchBranch(siblings[index + 1])}
                      >
                        ›
                      </button>
                    </span>
                  )}
                </div>

                {m.role === "user" &&
                  (editingId === m.id ? (
                    <div className="edit">
                      <textarea value={editText} onChange={(e) => setEditText(e.target.value)} rows={3} />
                      <div className="actions">
                        <button onClick={() => saveEdit(m.id)} disabled={!canAct || !editText.trim()}>
                          {t("chat.saveEdit")}
                        </button>
                        <button onClick={() => setEditingId(null)}>{t("chat.cancelEdit")}</button>
                      </div>
                    </div>
                  ) : (
                    <p className="user-text">{m.content}</p>
                  ))}

                {m.role === "assistant" && m.status === "streaming" && (
                  <StageLine progress={prog} trace={m.trace} actorLabel={(a) => code("actor", a)} />
                )}
                {m.role === "assistant" && m.content && (
                  <Answer content={m.content} trace={m.trace} onCite={citeFor(m.id)} />
                )}

                {m.status === "cancelled" && <small className="tag">{t("chat.stopped")}</small>}
                {m.status === "error" && <small className="tag error">⚠ {t("chat.interrupted")}</small>}

                {m.final && <Explainer f={m.final} onCite={citeFor(m.id)} />}
                {m.role === "assistant" && (
                  <Trace
                    trace={m.trace}
                    open={view.open}
                    highlight={view.highlight}
                    focus={view.focus}
                    onToggle={(open) =>
                      setTraceView((v) => (v[m.id]?.open === open ? v : { ...v, [m.id]: { ...(v[m.id] ?? CLOSED_TRACE), open } }))
                    }
                  />
                )}

                <div className="actions">
                  {m.role === "user" && editingId !== m.id && (
                    <button
                      disabled={!canAct}
                      onClick={() => {
                        setEditingId(m.id);
                        setEditText(m.content);
                      }}
                    >
                      {t("chat.edit")}
                    </button>
                  )}
                  {m.role === "assistant" && m.status !== "streaming" && (
                    <button disabled={!canAct} onClick={() => regenerate(m.id)}>
                      {t("chat.regenerate")}
                    </button>
                  )}
                </div>
              </article>
            );
          })}
          {error && (
            <p className="error" role="alert">
              <span aria-hidden="true">⚠</span> {t(error.key, error.vars)}
              {error.detail && <span lang="en">{`: ${error.detail}`}</span>}
            </p>
          )}
        </section>
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            sendMessage();
          }}
        >
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t("chat.placeholder")}
            aria-label={t("chat.inputLabel")}
            disabled={generating}
          />
          {generating ? (
            <button type="button" className="btn btn-secondary" onClick={cancel}>
              {t("chat.stop")}
            </button>
          ) : (
            <button type="submit" className="btn btn-primary" disabled={!canAct || !text.trim()}>
              {t("chat.send")}
            </button>
          )}
        </form>
        <p className="composer-note">{t("app.disclaimer")}</p>
      </main>
    </div>
  );
}

/** What the pipeline is doing now, with the number of trace steps so far and the latest one. */
function StageLine({
  progress,
  trace,
  actorLabel,
}: {
  progress: Progress | undefined;
  trace: TraceStep[];
  actorLabel: (actor: string) => string;
}) {
  const { t } = useI18n();
  const stage = progress?.stage ?? "planning";
  const last = trace[trace.length - 1];
  return (
    <div className="stage" role="status">
      <span className="typing" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <div>
        <strong>{t(`stage.${stage}` as Key, { n: Math.max(progress?.steps ?? 0, trace.length) })}</strong>
        {last && (
          <small>
            {last.step}. {actorLabel(last.actor)} · <code>{last.action}</code>
          </small>
        )}
        <small className="muted">{t("stage.note")}</small>
      </div>
    </div>
  );
}

/** Messages from the root down to `leafId`, following parentId. */
function activePath(all: Message[], leafId: string | null): Message[] {
  const byId = new Map(all.map((m) => [m.id, m]));
  const out: Message[] = [];
  let cur = leafId ? byId.get(leafId) : undefined;
  while (cur) {
    out.unshift(cur);
    cur = cur.parentId ? byId.get(cur.parentId) : undefined;
  }
  return out;
}

/** Messages with the same parent and role, in creation order (includes `m`). */
function siblingsOf(all: Message[], m: Message): Message[] {
  return all.filter((x) => x.parentId === m.parentId && x.role === m.role);
}

/** Follow the most recently created child until there is none. */
function latestLeaf(all: Message[], from: Message): Message {
  let cur = from;
  for (;;) {
    const children = all.filter((x) => x.parentId === cur.id);
    if (children.length === 0) return cur;
    cur = children[children.length - 1];
  }
}

/** Insert or replace a trace step by its number (steps can arrive again after a reload). */
function upsertStep(trace: TraceStep[], step: TraceStep): TraceStep[] {
  const i = trace.findIndex((s) => s.step === step.step);
  if (i === -1) return [...trace, step].sort((a, b) => a.step - b.step);
  const next = trace.slice();
  next[i] = step;
  return next;
}

function reduce(prev: Message[], m: WsServerMessage): Message[] {
  switch (m.type) {
    case "message.start": {
      const added = [...(m.userMessage ? [m.userMessage] : []), m.message];
      return [...prev.filter((x) => !added.some((a) => a.id === x.id)), ...added];
    }
    case "trace.step":
      return prev.map((x) => (x.id === m.messageId ? { ...x, trace: upsertStep(x.trace, m.step) } : x));
    case "message.delta":
      return prev.map((x) => (x.id === m.messageId ? { ...x, content: x.content + m.delta } : x));
    case "message.end":
      return prev.some((x) => x.id === m.message.id)
        ? prev.map((x) => (x.id === m.message.id ? m.message : x))
        : [...prev, m.message];
    default:
      return prev;
  }
}
