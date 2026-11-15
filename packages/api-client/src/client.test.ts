import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatSocket, createApiClient, type WsServerMessage } from "./index.js";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.onclose?.();
  }
  open() {
    this.onopen?.();
  }
  receive(msg: unknown) {
    this.onmessage?.({ data: typeof msg === "string" ? msg : JSON.stringify(msg) });
  }
}

const Impl = FakeWebSocket as unknown as typeof WebSocket;

describe("createApiClient", () => {
  it("sends the Bearer token and calls the right path", async () => {
    const fetchMock = vi.fn(async (req: Request) => {
      return new Response(JSON.stringify({ id: "u1", email: "a@b.co" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    const api = createApiClient({
      baseUrl: "http://api.test",
      getToken: () => "tok123",
      fetch: fetchMock as unknown as typeof fetch,
    });

    const { data, error } = await api.GET("/me");

    expect(error).toBeUndefined();
    expect(data?.email).toBe("a@b.co");
    const req = fetchMock.mock.calls[0]![0] as Request;
    expect(req.url).toBe("http://api.test/me");
    expect(req.headers.get("Authorization")).toBe("Bearer tok123");
  });

  it("omits Authorization when signed out", async () => {
    const fetchMock = vi.fn(
      async () => new Response("{}", { status: 401, headers: { "Content-Type": "application/json" } }),
    );
    const api = createApiClient({
      baseUrl: "http://api.test",
      getToken: () => null,
      fetch: fetchMock as unknown as typeof fetch,
    });
    await api.GET("/me");
    const req = fetchMock.mock.calls[0]![0] as unknown as Request;
    expect(req.headers.has("Authorization")).toBe(false);
  });
});

describe("ChatSocket", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  function make(overrides = {}) {
    return new ChatSocket({
      url: "ws://api.test/ws",
      getTicket: async () => "tick et",
      WebSocketImpl: Impl,
      ...overrides,
    });
  }

  it("connects with an encoded ticket and reports status", async () => {
    const socket = make();
    const statuses: string[] = [];
    socket.onStatus((s) => statuses.push(s));

    await socket.connect();
    const ws = FakeWebSocket.instances[0]!;
    expect(ws.url).toBe("ws://api.test/ws?ticket=tick%20et");
    ws.open();

    expect(statuses).toEqual(["connecting", "open"]);
  });

  it("sends typed messages and delivers server messages, hiding pong", async () => {
    const socket = make();
    const received: WsServerMessage[] = [];
    socket.onMessage((m) => received.push(m));
    await socket.connect();
    const ws = FakeWebSocket.instances[0]!;
    ws.open();

    socket.send({
      type: "message.send",
      conversationId: "11111111-1111-1111-1111-111111111111",
      text: "hello",
    });
    expect(JSON.parse(ws.sent[0]!)).toMatchObject({ type: "message.send", text: "hello" });

    ws.receive({ type: "pong" });
    ws.receive({
      type: "message.delta",
      conversationId: "c",
      messageId: "m",
      delta: "Hi",
    });
    ws.receive("not json");

    expect(received).toHaveLength(1);
    expect(received[0]).toMatchObject({ type: "message.delta", delta: "Hi" });
  });

  it("throws when sending while not open", () => {
    const socket = make();
    expect(() => socket.send({ type: "ping" })).toThrow("not open");
  });

  it("sends a ping on the heartbeat interval", async () => {
    const socket = make({ pingIntervalMs: 1000 });
    await socket.connect();
    const ws = FakeWebSocket.instances[0]!;
    ws.open();

    vi.advanceTimersByTime(2100);

    expect(ws.sent.map((s) => JSON.parse(s).type)).toEqual(["ping", "ping"]);
  });

  it("reconnects with a new ticket after an unexpected close", async () => {
    let n = 0;
    const getTicket = vi.fn(async () => `t${++n}`);
    const socket = make({ getTicket });
    await socket.connect();
    FakeWebSocket.instances[0]!.open();

    FakeWebSocket.instances[0]!.close(); // server dropped us
    expect(socket.currentStatus).toBe("reconnecting");

    await vi.advanceTimersByTimeAsync(1000);
    expect(getTicket).toHaveBeenCalledTimes(2);
    expect(FakeWebSocket.instances[1]!.url).toContain("ticket=t2");
  });

  it("does not reconnect after close()", async () => {
    const socket = make();
    await socket.connect();
    FakeWebSocket.instances[0]!.open();

    socket.close();
    await vi.advanceTimersByTimeAsync(60000);

    expect(socket.currentStatus).toBe("closed");
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
