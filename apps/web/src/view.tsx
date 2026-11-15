import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

// Global "Simple / Detailed" switch. It sets the default of the two toggles under every answer
// ("Show full analysis" and "Show the evidence"): Simple = both closed, Detailed = both open.

export type ViewMode = "simple" | "detailed";

const KEY = "viewMode";

function initialMode(): ViewMode {
  try {
    return localStorage.getItem(KEY) === "detailed" ? "detailed" : "simple";
  } catch {
    return "simple"; // storage unavailable
  }
}

const Ctx = createContext<{ mode: ViewMode; setMode: (m: ViewMode) => void } | null>(null);

export function ViewModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ViewMode>(initialMode);
  const setMode = useCallback((m: ViewMode) => {
    setModeState(m);
    try {
      localStorage.setItem(KEY, m);
    } catch {
      /* storage unavailable: the choice still applies for this visit */
    }
  }, []);
  const value = useMemo(() => ({ mode, setMode }), [mode, setMode]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useViewMode() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useViewMode outside ViewModeProvider");
  return ctx;
}
