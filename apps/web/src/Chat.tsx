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
import { AppBar, Footer } from "./AppBar";
import { Evidence, Recommended } from "./Explainer";
import { refreshHealth, useHealth } from "./health";
import { useI18n, type Key } from "./i18n";
import { personaById } from "./personas";
import { answerTone } from "./Status";
import { Trace } from "./Trace";
import { useViewMode } from "./view";

interface Progress {
  stage: GenerationStage;
  steps: number;
}

interface TraceView {
  open: boolean;
  highlight: number[];
  focus: number;
}

/** Per-answer toggles. `full` / `evidence` undefined = follow the global Simple / Detailed default. */
interface AnswerView {
  full?: boolean;
  evidence?: boolean;
  trace: TraceView;
}

interface ErrorState {
  key: Key;
  vars?: Record<string, string>;
  detail?: string;
}

const CLOSED_TRACE: TraceView = { open: false, highlight: [], focus: 0 };
const SUGGESTIONS = [1, 2, 3] as const;
// The four steps shown in the progress line; each server stage maps to one of them.
const PHASES = ["planning", "analyzing", "reviewing", "writing"] as const;
const PHASE_OF: Record<GenerationStage, number> = {
  queued: 0, planning: 0, analyzing: 1, reviewing: 2, writing: 3, checking: 3, done: 4,
};
const DEFAULT_VIEW: AnswerView = { trace: CLOSED_TRACE };

export function Chat({ personaId, onBack }: { personaId: PersonaId; onBack: () => void }) {
  const { t, lang, code } = useI18n();
  const health = useHealth();
  const { mode } = useViewMode();
  const detailed = mode === "detailed";
  const persona = personaById(personaId);
  const name = persona?.name ?? personaId;

  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]); // every branch
  const [activeLeafId, setActiveLeafId] = useState<string | null>(null);
  const [progress, setProgress] = useState<Record<string, Progress>>({});
  const [views, setViews] = useState<Record<string, AnswerView>>({});
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
  // The backend may have restarted in another mode (demo / Bedrock): re-check /health on every (re)connect.
  useEffect(() => {
    if (status === "open") void refreshHealth();
  }, [status]);

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

  // Changing Simple / Detailed resets every answer's two toggles to the new default.
  useEffect(() => {
    setViews((v) => Object.fromEntries(Object.entries(v).map(([id, x]) => [id, { trace: x.trace }])));
  }, [mode]);

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
      // A cited step lives in the trace, inside the evidence: open both.
      fn = (steps: number[]) =>
        setViews((v) => {
          const cur = v[id] ?? DEFAULT_VIEW;
          return { ...v, [id]: { ...cur, evidence: true, trace: { open: true, highlight: steps, focus: cur.trace.focus + 1 } } };
        });
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

  return (
    <div className={`page chat-page view-${mode}`}>
      <AppBar
        showView
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
              <span className={`avatar avatar-lg avatar-${personaId}`} aria-hidden="true">
                {name[0]}
              </span>
              <h2>{t("chat.emptyTitle", { name })}</h2>
              <p>{t("chat.emptyHint", { name })}</p>
            </div>
          )}
          {path.map((m) => {
            const siblings = siblingsOf(messages, m);
            const index = siblings.findIndex((s) => s.id === m.id);
            const view = views[m.id] ?? DEFAULT_VIEW;
            const showFull = view.full ?? detailed;
            const showEvidence = view.evidence ?? detailed;
            const prog = progress[m.id];
            const setView = (patch: Partial<AnswerView>) =>
              setViews((v) => ({ ...v, [m.id]: { ...(v[m.id] ?? DEFAULT_VIEW), ...patch } }));
            const trace = m.role === "assistant" && (
              <Trace
                trace={m.trace}
                open={view.trace.open}
                highlight={view.trace.highlight}
                focus={view.trace.focus}
                onToggle={(open) => {
                  if (view.trace.open !== open) setView({ trace: { ...view.trace, open } });
                }}
              />
            );
            const evidenceId = `evidence-${m.id}`;
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

                {m.role === "assistant" && (
                  <div className={m.final ? "msg-grid" : undefined}>
                    <div className="msg-main">
                      {m.status === "streaming" && (
                        <ProgressLine progress={prog} trace={m.trace} actorLabel={(a) => code("actor", a)} />
                      )}
                      {m.status === "streaming" && !m.content && <Skeleton />}
                      {m.content && (
                        <Answer
                          id={m.id}
                          content={m.content}
                          trace={m.trace}
                          onCite={citeFor(m.id)}
                          showFull={showFull}
                          onToggleFull={() => setView({ full: !showFull })}
                          tone={answerTone(m.final)}
                          streaming={m.status === "streaming"}
                        />
                      )}
                      {m.status === "cancelled" && <small className="tag">{t("chat.stopped")}</small>}
                      {m.status === "error" && <small className="tag error">⚠ {t("chat.interrupted")}</small>}
                      {!m.final && trace}
                    </div>
                    {m.final && (
                      <aside className="msg-evidence">
                        <Recommended f={m.final} onCite={citeFor(m.id)} />
                        <button
                          type="button"
                          className="toggle toggle-evidence"
                          aria-expanded={showEvidence}
                          aria-controls={evidenceId}
                          onClick={() => setView({ evidence: !showEvidence })}
                        >
                          <span className="toggle-icon" aria-hidden="true">
                            {showEvidence ? "▾" : "▸"}
                          </span>
                          <span>
                            {showEvidence ? t("ev.hide") : t("ev.show")}
                            {!showEvidence && <small>{t("ev.hint")}</small>}
                          </span>
                        </button>
                        {showEvidence && (
                          <div id={evidenceId}>
                            <Evidence f={m.final} onCite={citeFor(m.id)}>
                              {trace}
                            </Evidence>
                          </div>
                        )}
                      </aside>
                    )}
                  </div>
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
        <div className="suggestions" role="group" aria-label={t("sug.label")}>
          {SUGGESTIONS.map((i) => {
            const q = t(`sug.${personaId}.${i}` as Key);
            return (
              <button key={i} type="button" className="suggestion" disabled={!canAct} onClick={() => sendMessage(q)}>
                {q}
              </button>
            );
          })}
        </div>
        <Footer />
      </main>
    </div>
  );
}

/** Slim progress line (Planning -> Analysing -> Reviewing -> Writing), the current stage text and latest step. */
function ProgressLine({
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
  const current = PHASE_OF[stage] ?? 0;
  const last = trace[trace.length - 1];
  return (
    <div className="progress" role="status">
      <ol className="progress-steps" aria-label={t("prog.label")}>
        {PHASES.map((p, i) => (
          <li key={p} className={i < current ? "done" : i === current ? "current" : ""}
            aria-current={i === current ? "step" : undefined}>
            <span className="progress-bar" aria-hidden="true" />
            <span className="progress-name">{t(`prog.${p}`)}</span>
          </li>
        ))}
      </ol>
      <p className="progress-text">
        {t(`stage.${stage}` as Key, { n: Math.max(progress?.steps ?? 0, trace.length) })}
        {last && (
          <small>
            {" "}
            · {last.step}. {actorLabel(last.actor)}
          </small>
        )}
      </p>
    </div>
  );
}

/** Grey placeholder lines until the first answer text arrives. */
function Skeleton() {
  return (
    <div className="skeleton" aria-hidden="true">
      <span style={{ width: "38%" }} />
      <span style={{ width: "92%" }} />
      <span style={{ width: "84%" }} />
      <span style={{ width: "66%" }} />
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
      // Streamed text; `reset` = the reviewer asked for a rewrite (or the server replaced the text)
      return prev.map((x) => (x.id === m.messageId ? { ...x, content: (m.reset ? "" : x.content) + m.delta } : x));
    case "message.end":
      return prev.some((x) => x.id === m.message.id)
        ? prev.map((x) => (x.id === m.message.id ? m.message : x))
        : [...prev, m.message];
    default:
      return prev;
  }
}
