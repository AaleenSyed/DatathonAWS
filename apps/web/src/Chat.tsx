import { useEffect, useMemo, useRef, useState } from "react";
import type { Message, PersonaId, SocketStatus, ToolCall, WsServerMessage } from "@alphaforge/api-client";
import { api, createChatSocket } from "./api";
import { AppBar } from "./AppBar";

const STATUS_LABEL: Record<SocketStatus, string> = {
  idle: "Inactif",
  connecting: "Connexion…",
  open: "Connecté",
  reconnecting: "Reconnexion…",
  closed: "Déconnecté",
};

// Contract values stay in English in the data; these are their French display labels.
const CLAIM_LABEL: Record<string, string> = { fact: "Fait", assumption: "Hypothèse", scenario: "Scénario" };
const TOOL_STATUS_LABEL: Record<string, string> = { running: "en cours", ok: "terminé", error: "erreur" };
const TOOL_LABEL: Record<string, string> = {
  data_retriever: "Collecte des données",
  risk_analyst: "Analyse du risque",
  suitability: "Vérification de la convenance",
  market_context: "Contexte de marché",
};

export function Chat({ personaId, onBack }: { personaId: PersonaId; onBack: () => void }) {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]); // every branch
  const [activeLeafId, setActiveLeafId] = useState<string | null>(null);
  const [status, setStatus] = useState<SocketStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const socket = useRef(createChatSocket());
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const s = socket.current;
    const offStatus = s.onStatus(setStatus);
    const offMsg = s.onMessage((m) => {
      setMessages((prev) => reduce(prev, m));
      if (m.type === "message.start") setActiveLeafId(m.message.id);
      if (m.type === "error") {
        setError(`${m.code}: ${m.message}`);
        setMessages((prev) => failStreaming(prev));
      }
    });
    (async () => {
      const { data, error: err } = await api.POST("/conversations", { body: { personaId } });
      if (err || !data) return setError("Impossible de créer la conversation.");
      setConversationId(data.id);
      await s.connect();
    })().catch((e) => setError(String(e)));
    return () => {
      offStatus();
      offMsg();
      s.close();
    };
  }, [personaId]);

  // A dropped connection ends any generation in progress.
  useEffect(() => {
    if (status === "reconnecting" || status === "closed") setMessages((prev) => failStreaming(prev));
  }, [status]);

  const path = useMemo(() => activePath(messages, activeLeafId), [messages, activeLeafId]);
  const generating = messages.some((m) => m.status === "streaming");

  // Keep the newest text in view while an answer streams in.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, generating, path[path.length - 1]?.content.length]);
  const canAct = status === "open" && !!conversationId && !generating;

  function sendMessage() {
    const value = text.trim();
    if (!value || !canAct) return;
    setError(null);
    socket.current.send({ type: "message.send", conversationId: conversationId!, text: value });
    setText("");
  }

  function saveEdit(messageId: string) {
    const value = editText.trim();
    if (!value || !canAct) return;
    setError(null);
    socket.current.send({ type: "message.edit", conversationId: conversationId!, messageId, text: value });
    setEditingId(null);
  }

  function regenerate(messageId: string) {
    if (!canAct) return;
    setError(null);
    socket.current.send({ type: "message.regenerate", conversationId: conversationId!, messageId });
  }

  function cancel() {
    if (conversationId) socket.current.send({ type: "generation.cancel", conversationId });
  }

  async function switchBranch(sibling: Message) {
    if (generating || !conversationId) return;
    const leaf = latestLeaf(messages, sibling);
    setActiveLeafId(leaf.id);
    const { error: err } = await api.PATCH("/conversations/{conversationId}", {
      params: { path: { conversationId } },
      body: { activeLeafId: leaf.id },
    });
    if (err) setError("Impossible d’afficher cette version.");
  }

  return (
    <div className="page chat-page">
      <AppBar
        left={
          <>
            <button className="back" onClick={onBack}>
              <span aria-hidden="true">←</span> Changer de profil
            </button>
            <span className="persona-name">Agent</span>
          </>
        }
        right={
          <span className={`status status-${status}`} role="status">
            <span className="dot" aria-hidden="true" />
            {STATUS_LABEL[status] ?? status}
          </span>
        }
      />
      <main className="chat">
      <section className="messages" aria-live="polite">
        {path.length === 0 && !error && (
          <div className="empty">
            <h2>Posez une question à l’Agent</h2>
            <p>Essayez « Comment répartir mon portefeuille? » ou « Quel est le risque de ne détenir que des actions technologiques? »</p>
          </div>
        )}
        {path.map((m) => {
          const siblings = siblingsOf(messages, m);
          const index = siblings.findIndex((s) => s.id === m.id);
          return (
            <article key={m.id} className={`msg ${m.role}`}>
              <div className="msg-role">{m.role === "user" ? "Vous" : "Agent"}</div>
              {siblings.length > 1 && (
                <div className="branches" aria-label="Autres versions de ce message">
                  <button
                    aria-label="Version précédente"
                    disabled={generating || index === 0}
                    onClick={() => switchBranch(siblings[index - 1])}
                  >
                    ‹
                  </button>
                  <span>
                    {index + 1}/{siblings.length}
                  </span>
                  <button
                    aria-label="Version suivante"
                    disabled={generating || index === siblings.length - 1}
                    onClick={() => switchBranch(siblings[index + 1])}
                  >
                    ›
                  </button>
                </div>
              )}

              {editingId === m.id ? (
                <div className="edit">
                  <textarea value={editText} onChange={(e) => setEditText(e.target.value)} rows={3} />
                  <div className="actions">
                    <button onClick={() => saveEdit(m.id)} disabled={!canAct || !editText.trim()}>
                      Enregistrer et renvoyer
                    </button>
                    <button onClick={() => setEditingId(null)}>Annuler la modification</button>
                  </div>
                </div>
              ) : (
                <p>
                  {m.content}
                  {m.status === "streaming" && !m.content && (
                    <span className="typing" aria-label="Réflexion en cours">
                      <i />
                      <i />
                      <i />
                    </span>
                  )}
                </p>
              )}

              {m.status === "cancelled" && <small className="tag">Arrêté</small>}
              {m.status === "error" && <small className="tag error">⚠ Interrompu</small>}

              {m.toolCalls.length > 0 && (
                <details>
                  <summary>Trace ({m.toolCalls.length} étapes)</summary>
                  <ul>
                    {m.toolCalls.map((t) => (
                      <li key={t.id}>
                        {TOOL_LABEL[t.name] ?? t.name} <em>{TOOL_STATUS_LABEL[t.status] ?? t.status}</em>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {m.final && (
                <details>
                  <summary>Pourquoi cette réponse</summary>
                  <p>{m.final.summary}</p>
                  <ul>
                    {m.final.claims.map((c, i) => (
                      <li key={i}>
                        [{CLAIM_LABEL[c.kind] ?? c.kind}] {c.text} {c.source && <small>({c.source})</small>}
                      </li>
                    ))}
                  </ul>
                  {m.final.governance.length > 0 && (
                    <ul>
                      {m.final.governance.map((g, i) => (
                        <li key={i}>
                          {g.status === "flag" ? "⚠" : "✓"} {g.rule}
                          {g.note ? `: ${g.note}` : ""}
                        </li>
                      ))}
                    </ul>
                  )}
                  {m.final.limitations.length > 0 && <p>Limites : {m.final.limitations.join("; ")}</p>}
                </details>
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
                    Modifier
                  </button>
                )}
                {m.role === "assistant" && m.status !== "streaming" && (
                  <button disabled={!canAct} onClick={() => regenerate(m.id)}>
                    Régénérer
                  </button>
                )}
              </div>
            </article>
          );
        })}
        {error && (
          <p className="error" role="alert">
            <span aria-hidden="true">⚠</span> {error}
          </p>
        )}
        <div ref={endRef} />
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
          placeholder="Posez une question…"
          aria-label="Votre question"
          disabled={generating}
        />
        {generating ? (
          <button type="button" className="btn btn-secondary" onClick={cancel}>
            Arrêter
          </button>
        ) : (
          <button type="submit" className="btn btn-primary" disabled={!canAct}>
            Envoyer
          </button>
        )}
      </form>
      </main>
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

function failStreaming(prev: Message[]): Message[] {
  return prev.some((m) => m.status === "streaming")
    ? prev.map((m) => (m.status === "streaming" ? { ...m, status: "error" as const } : m))
    : prev;
}

function upsertTool(calls: ToolCall[], call: ToolCall): ToolCall[] {
  return calls.some((c) => c.id === call.id) ? calls.map((c) => (c.id === call.id ? call : c)) : [...calls, call];
}

function reduce(prev: Message[], m: WsServerMessage): Message[] {
  switch (m.type) {
    case "message.start":
      return [...prev, ...(m.userMessage ? [m.userMessage] : []), m.message];
    case "message.delta":
      return prev.map((x) => (x.id === m.messageId ? { ...x, content: x.content + m.delta } : x));
    case "tool.call":
    case "tool.result":
      return prev.map((x) => (x.id === m.messageId ? { ...x, toolCalls: upsertTool(x.toolCalls, m.toolCall) } : x));
    case "message.end":
      return prev.map((x) => (x.id === m.message.id ? m.message : x));
    default:
      return prev;
  }
}
