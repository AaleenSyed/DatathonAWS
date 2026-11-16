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

// Text size of the assistant's answers (A− / A+ in the chat header). Stored per browser; applied as the CSS variable
// --answer-zoom on <html>, which styles.css uses to zoom the assistant bubble (text, tables and charts together).
export const ANSWER_SCALES = [0.6, 0.75, 0.9, 1, 1.15, 1.3, 1.5] as const;
const SCALE_KEY = "answerScale";

function initialScale(): number {
  try {
    const v = Number(localStorage.getItem(SCALE_KEY));
    return (ANSWER_SCALES as readonly number[]).includes(v) ? v : 1;
  } catch {
    return 1;
  }
}

function applyScale(s: number) {
  document.documentElement.style.setProperty("--answer-zoom", String(s));
}

export function useAnswerScale(): [number, (s: number) => void] {
  const [scale, setScaleState] = useState(() => {
    const s = initialScale();
    applyScale(s);
    return s;
  });
  const setScale = useCallback((s: number) => {
    setScaleState(s);
    applyScale(s);
    try {
      localStorage.setItem(SCALE_KEY, String(s));
    } catch {
      /* storage unavailable: the size still applies for this visit */
    }
  }, []);
  return [scale, setScale];
}
