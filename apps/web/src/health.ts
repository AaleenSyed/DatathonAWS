import { useEffect, useState } from "react";
import type { Health } from "@alphaforge/api-client";
import { api } from "./api";

let pending: Promise<Health | null> | null = null;

/** GET /health once per page load (agent mode for the demo banner). Null until it answers or if it fails. */
export function useHealth(): Health | null {
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => {
    pending ??= api
      .GET("/health")
      .then(({ data }) => data ?? null)
      .catch(() => null);
    let live = true;
    void pending.then((h) => live && setHealth(h));
    return () => {
      live = false;
    };
  }, []);
  return health;
}
