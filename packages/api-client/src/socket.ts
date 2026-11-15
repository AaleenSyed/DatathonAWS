import type { WsClientMessage, WsServerMessage } from "./types.js";

export type SocketStatus = "idle" | "connecting" | "open" | "reconnecting" | "closed";

export interface ChatSocketOptions {
  /** WebSocket endpoint without query string, e.g. ws://localhost:8000/ws */
  url: string;
  /** Fetches a fresh single-use ticket (POST /ws-ticket). Called before every (re)connect. */
  getTicket: () => Promise<string>;
  /** Override for tests or non-standard runtimes. Defaults to the global WebSocket. */
  WebSocketImpl?: typeof WebSocket;
  /** Heartbeat interval. The contract asks for a ping every 25 seconds. */
  pingIntervalMs?: number;
  /** Reconnect automatically after an unexpected close. Default true. */
  reconnect?: boolean;
  /** Maximum delay between reconnect attempts. Default 15000. */
  maxBackoffMs?: number;
}

type MessageListener = (message: WsServerMessage) => void;
type StatusListener = (status: SocketStatus) => void;

/**
 * Typed WebSocket for the chat protocol (contracts/asyncapi.yaml).
 * Works with the browser WebSocket and React Native's WebSocket.
 */
export class ChatSocket {
  private ws: WebSocket | null = null;
  private status: SocketStatus = "idle";
  private attempts = 0;
  private intentionalClose = false;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private messageListeners = new Set<MessageListener>();
  private statusListeners = new Set<StatusListener>();

  constructor(private readonly options: ChatSocketOptions) {}

  get currentStatus(): SocketStatus {
    return this.status;
  }

  /** Subscribe to server messages. Returns an unsubscribe function. `pong` is not forwarded. */
  onMessage(listener: MessageListener): () => void {
    this.messageListeners.add(listener);
    return () => this.messageListeners.delete(listener);
  }

  /** Subscribe to connection status changes. Returns an unsubscribe function. */
  onStatus(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  async connect(): Promise<void> {
    if (this.status === "open" || this.status === "connecting") return;
    this.intentionalClose = false;
    this.setStatus(this.attempts > 0 ? "reconnecting" : "connecting");

    let ticket: string;
    try {
      ticket = await this.options.getTicket();
    } catch (err) {
      this.scheduleReconnect();
      if (!this.shouldReconnect()) throw err;
      return;
    }
    if (this.intentionalClose) return;

    const Impl = this.options.WebSocketImpl ?? WebSocket;
    const ws = new Impl(`${this.options.url}?ticket=${encodeURIComponent(ticket)}`);
    this.ws = ws;

    ws.onopen = () => {
      this.attempts = 0;
      this.setStatus("open");
      this.startHeartbeat();
    };
    ws.onmessage = (event: MessageEvent) => this.handleRaw(event.data);
    ws.onclose = () => {
      this.stopHeartbeat();
      this.ws = null;
      if (this.intentionalClose) this.setStatus("closed");
      else this.scheduleReconnect();
    };
    ws.onerror = () => {
      // A close event always follows; reconnect logic lives there.
    };
  }

  /** Send a typed client message. Throws if the socket is not open. */
  send(message: WsClientMessage): void {
    if (!this.ws || this.status !== "open") {
      throw new Error("ChatSocket is not open");
    }
    this.ws.send(JSON.stringify(message));
  }

  close(): void {
    this.intentionalClose = true;
    this.stopHeartbeat();
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    if (this.ws) this.ws.close(1000);
    else this.setStatus("closed");
  }

  private handleRaw(data: unknown): void {
    if (typeof data !== "string") return;
    let parsed: WsServerMessage;
    try {
      parsed = JSON.parse(data) as WsServerMessage;
    } catch {
      return;
    }
    if (!parsed || typeof parsed !== "object" || !("type" in parsed)) return;
    if (parsed.type === "pong") return;
    for (const listener of this.messageListeners) listener(parsed);
  }

  private shouldReconnect(): boolean {
    return (this.options.reconnect ?? true) && !this.intentionalClose;
  }

  private scheduleReconnect(): void {
    if (!this.shouldReconnect()) {
      this.setStatus("closed");
      return;
    }
    const max = this.options.maxBackoffMs ?? 15000;
    const base = Math.min(max, 500 * 2 ** this.attempts);
    const delay = base / 2 + Math.random() * (base / 2);
    this.attempts += 1;
    this.setStatus("reconnecting");
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect();
    }, delay);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.pingTimer = setInterval(() => {
      if (this.ws && this.status === "open") {
        this.ws.send(JSON.stringify({ type: "ping" } satisfies WsClientMessage));
      }
    }, this.options.pingIntervalMs ?? 25000);
  }

  private stopHeartbeat(): void {
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.pingTimer = null;
  }

  private setStatus(status: SocketStatus): void {
    if (this.status === status) return;
    this.status = status;
    for (const listener of this.statusListeners) listener(status);
  }
}
