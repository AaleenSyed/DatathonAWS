import { useEffect, useState } from "react";
import type { Health } from "@alphaforge/api-client";
import { api } from "./api";

// GET /health, shared by every component (demo-mode banner). Re-checked every 30 s while a component uses it,
// and whenever the chat WebSocket (re)connects (refreshHealth), so the banner follows a backend restarted
// in another mode. Null until the first answer, or while the backend does not answer.

const INTERVAL_MS = 30_000;
let current: Health | null = null;
let inflight: Promise<void> | null = null;
let timer: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<(h: Health | null) => void>();

function same(a: Health | null, b: Health | null): boolean {
  return a?.status === b?.status && a?.agentMode === b?.agentMode && a?.authMode === b?.authMode;
}

/** Fetch /health now (one request at a time) and notify every user of useHealth. */
export function refreshHealth(): Promise<void> {
  inflight ??= api
    .GET("/health")
    .then(({ data }) => data ?? null)
    .catch(() => null)
    .then((h) => {
      inflight = null;
      if (same(h, current)) return;
      current = h;
      for (const l of listeners) l(h);
    });
  return inflight;
}

export function useHealth(): Health | null {
  const [health, setHealth] = useState<Health | null>(current);
  useEffect(() => {
    listeners.add(setHealth);
    setHealth(current);
    void refreshHealth();
    timer ??= setInterval(() => void refreshHealth(), INTERVAL_MS);
    return () => {
      listeners.delete(setHealth);
      if (!listeners.size && timer) {
        clearInterval(timer);
        timer = null;
      }
    };
  }, []);
  return health;
}
