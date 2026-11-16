import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  GenerationStage,
  Message,
  Persona,
  PersonaId,
  SocketStatus,
  TraceStep,
  WsClientMessage,
  WsServerMessage,
} from "@alphaforge/api-client";
import { ChatContainer, ChatInput, ChatMessage, TypingIndicator } from "@/registry/blocks/chat";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { api, createChatSocket } from "./api";
import { Answer } from "./Answer";
import { AgentAvatar, AppBar } from "./AppBar";
import { Evidence, Recommended } from "./Explainer";
import { refreshHealth, useHealth } from "./health";
import { useI18n, type Key } from "./i18n";
import { isCustomId, personaById } from "./personas";
import { ProfileCard, SparkAvatar } from "./ProfileBuilder";
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
  const custom = isCustomId(personaId);
  const [profile, setProfile] = useState<Persona | null>(null);
  const name = persona?.name ?? profile?.name ?? t("pf.name");

  // A custom profile lives in the server's memory: load it for the header and the profile card.
  useEffect(() => {
    if (!custom) return;
    let live = true;
    void api.GET("/profiles/{profileId}", { params: { path: { profileId: personaId } } }).then(({ data }) => {
      if (live && data) setProfile(data);
    });
    return () => {
      live = false;
    };
  }, [custom, personaId]);

  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]); // every branch
  const [activeLeafId, setActiveLeafId] = useState<string | null>(null);
  const [progress, setProgress] = useState<Record<string, Progress>>({});
  const [views, setViews] = useState<Record<string, AnswerView>>({});
  const [status, setStatus] = useState<SocketStatus>("idle");
  const [error, setError] = useState<ErrorState | null>(null);
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
      if (err || !data) return setError({ key: custom ? "pf.lost" : "chat.errCreate" });
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
    const calm = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    document.getElementById(`msg-${p.id}`)?.scrollIntoView({ block: p.block, behavior: calm ? "auto" : "smooth" });
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

  /** false = not sent (the message bar keeps the text). */
  function sendMessage(text: string): boolean {
    const value = text.trim();
    if (!value || !canAct) return false;
    return send({ type: "message.send", conversationId: conversationId!, text: value, language: lang });
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

  const demo = health?.agentMode === "demo";
  const suggestions = SUGGESTIONS.map((i) => t(`sug.${custom ? "custom" : personaId}.${i}` as Key));
  // The latest question and answer keep their buttons visible; older ones show them on hover / focus.
  const lastId = path[path.length - 1]?.id;
  const lastUserId = [...path].reverse().find((m) => m.role === "user")?.id;

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
      <main id="main" tabIndex={-1} className="flex min-h-0 flex-1 flex-col">
        <h1 className="sr-only">{t("chat.title", { name })}</h1>
        <ChatContainer busy={generating} logLabel={t("chat.log", { name })}>
          {demo && <ChatMessage role="system" content={t("app.demo")} />}
          {path.length === 0 && (
            <div className="m-auto flex w-full max-w-3xl flex-col items-center gap-3 py-6 text-center">
              {custom ? (
                <SparkAvatar large />
              ) : (
                <span className={`avatar avatar-lg avatar-${personaId}`} aria-hidden="true">
                  {name[0]}
                </span>
              )}
              <h2 className="text-[length:var(--step-3)] text-foreground">
                {t(custom ? "pf.emptyTitle" : "chat.emptyTitle", { name })}
              </h2>
              <p className="max-w-[46ch] text-base text-muted-foreground">
                {t(custom ? "pf.emptyHint" : "chat.emptyHint", { name })}
              </p>
              {profile && <ProfileCard p={profile} compact />}
              <div role="group" aria-labelledby="sug-label" className="mt-5 grid w-full gap-2.5 sm:grid-cols-3">
                <p
                  id="sug-label"
                  className="text-sm font-semibold text-muted-foreground sm:col-span-3"
                >
                  {t("sug.label")}
                </p>
                {suggestions.map((q) => (
                  <button
                    key={q}
                    type="button"
                    disabled={!canAct}
                    onClick={() => sendMessage(q)}
                    className={
                      "group/sug flex cursor-pointer items-start justify-between gap-3 rounded-lg border border-border " +
                      "min-h-11 bg-card p-4 text-left text-[0.95rem] leading-snug text-body shadow-sm " +
                      "transition-[border-color,color,transform] motion-safe:hover:-translate-y-0.5 hover:border-primary " +
                      "hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
                    }
                  >
                    <span>{q}</span>
                    <span aria-hidden="true" className="text-muted-foreground group-hover/sug:text-foreground">
                      ↗
                    </span>
                  </button>
                ))}
              </div>
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
            const versions = siblings.length > 1 && (
              <Versions
                index={index}
                total={siblings.length}
                disabled={generating}
                onPick={(i) => switchBranch(siblings[i])}
              />
            );

            if (m.role === "user") {
              const editing = editingId === m.id;
              return (
                <ChatMessage
                  key={m.id}
                  id={`msg-${m.id}`}
                  role="user"
                  className={cn("msg", editing && "w-full max-w-[min(100%,44rem)]")}
                  srLabel={t("chat.youSaid")}
                  meta={versions}
                  bubbleClassName={editing ? "w-full border border-input bg-card p-3 text-foreground" : undefined}
                  actionsVisible={m.id === lastUserId}
                  actions={
                    !editing && (
                      <button
                        type="button"
                        className={buttonVariants({ variant: "ghost", size: "xs" })}
                        disabled={!canAct}
                        onClick={() => {
                          setEditingId(m.id);
                          setEditText(m.content);
                        }}
                      >
                        <PencilIcon />
                        {t("chat.edit")}
                      </button>
                    )
                  }
                >
                  {editing ? (
                    <div className="flex flex-col gap-2">
                      <textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        rows={3}
                        autoFocus
                        aria-label={t("chat.inputLabel")}
                        className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-base text-foreground"
                      />
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          className={buttonVariants({ variant: "ghost", size: "sm" })}
                          onClick={() => setEditingId(null)}
                        >
                          {t("chat.cancelEdit")}
                        </button>
                        <button
                          type="button"
                          className={buttonVariants({ size: "sm" })}
                          onClick={() => saveEdit(m.id)}
                          disabled={!canAct || !editText.trim()}
                        >
                          {t("chat.saveEdit")}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{m.content}</p>
                  )}
                </ChatMessage>
              );
            }

            const trace = (
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
              <ChatMessage
                key={m.id}
                id={`msg-${m.id}`}
                role="assistant"
                className="msg"
                avatar={<AgentAvatar />}
                name={name}
                srLabel={t("chat.said", { name })}
                meta={versions}
                actionsVisible={m.id === lastId}
                actions={
                  m.status !== "streaming" && (
                    <button
                      type="button"
                      className={buttonVariants({ variant: "ghost", size: "xs" })}
                      disabled={!canAct}
                      onClick={() => regenerate(m.id)}
                    >
                      <RefreshIcon />
                      {t("chat.regenerate")}
                    </button>
                  )
                }
              >
                  <div>
                    <div className="msg-main">
                      {m.status === "streaming" && (
                        <ProgressLine progress={prog} trace={m.trace} actorLabel={(a) => code("actor", a)} />
                      )}
                      {m.status === "streaming" && !m.content && <TypingIndicator label={t("chat.thinking")} />}
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
                          afterSummary={m.final && <Recommended f={m.final} onCite={citeFor(m.id)} />}
                        />
                      )}
                      {m.status === "cancelled" && <small className="tag">{t("chat.stopped")}</small>}
                      {m.status === "error" && <small className="tag error">⚠ {t("chat.interrupted")}</small>}
                      {!m.final && trace}
                    </div>
                    {m.final && (
                      <aside className="msg-evidence">
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
              </ChatMessage>
            );
          })}
          {error && (
            <ChatMessage role="system" variant="destructive">
              <p>
                <span aria-hidden="true">⚠</span> {t(error.key, error.vars)}
                {error.detail && <span lang="en">{`: ${error.detail}`}</span>}
              </p>
            </ChatMessage>
          )}
          <ChatInput
            onSubmit={sendMessage}
            placeholder={t("chat.placeholder")}
            label={t("chat.inputLabel")}
            disabled={status !== "open" || !conversationId}
            isGenerating={generating}
            onStop={cancel}
            sendLabel={t("chat.send")}
            stopLabel={t("chat.stop")}
            hint={t("footer.text")}
          >
            {path.length > 0 && (
              <div
                role="group"
                aria-label={t("sug.label")}
                className="flex flex-wrap gap-2"
              >
                {suggestions.map((q) => (
                  <button
                    key={q}
                    type="button"
                    disabled={!canAct}
                    onClick={() => sendMessage(q)}
                    className={buttonVariants({ variant: "outline", size: "sm", className: "font-normal text-body" })}
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}
          </ChatInput>
        </ChatContainer>
      </main>
    </div>
  );
}

/** "‹ 2/3 ›": switch between the versions of a message (edit / regenerate create new versions). */
function Versions({
  index,
  total,
  disabled,
  onPick,
}: {
  index: number;
  total: number;
  disabled: boolean;
  onPick: (index: number) => void;
}) {
  const { t } = useI18n();
  const btn = buttonVariants({ variant: "ghost", size: "icon-sm", className: "text-base" });
  return (
    <span role="group" aria-label={t("chat.versions")} className="inline-flex items-center gap-0.5 text-xs text-muted-foreground tabular-nums">
      <button type="button" className={btn} aria-label={t("chat.prev")} disabled={disabled || index === 0} onClick={() => onPick(index - 1)}>
        ‹
      </button>
      <span>
        {index + 1}/{total}
      </span>
      <button
        type="button"
        className={btn}
        aria-label={t("chat.next")}
        disabled={disabled || index === total - 1}
        onClick={() => onPick(index + 1)}
      >
        ›
      </button>
    </span>
  );
}

function PencilIcon() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12a9 9 0 1 1-2.6-6.4M21 4v5h-5" />
    </svg>
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
