import type { ExplainerPayload } from "@alphaforge/api-client";
import { useI18n } from "./i18n";

// One status pill for every place a suitability status appears (cards, tables, review, hero card):
// pass = green check, flag / incomplete = amber "!" (labelled "Caution"), conflict = red cross,
// info = neutral "i", not applicable / not evaluated = plain grey.

export type Tone = "pass" | "caution" | "conflict" | "info" | "neutral";

export function toneOf(status: string | null | undefined): Tone {
  switch (status) {
    case "pass":
      return "pass";
    case "flag":
    case "incomplete":
      return "caution";
    case "conflict":
      return "conflict";
    case "info":
      return "info";
    default:
      return "neutral";
  }
}

/** Overall tone of an answer: any conflict -> conflict; any flag (or incomplete) -> caution; else pass. */
export function answerTone(f: ExplainerPayload | null | undefined): Tone {
  if (!f) return "neutral";
  const overall = f.suitability.map((s) => s.overall);
  if (overall.includes("conflict")) return "conflict";
  if (overall.includes("flag") || overall.includes("incomplete") || f.review.incomplete) return "caution";
  return "pass";
}

export function ToneIcon({ tone }: { tone: Tone }) {
  if (tone === "neutral") return null;
  const path = {
    pass: <path d="M4.5 8.3l2.2 2.2 4.8-5" />,
    caution: (
      <>
        <path d="M8 4.4v4.2" />
        <circle cx="8" cy="11.3" r=".35" fill="currentColor" />
      </>
    ),
    conflict: <path d="M5.4 5.4l5.2 5.2M10.6 5.4l-5.2 5.2" />,
    info: (
      <>
        <path d="M8 7.2v4.3" />
        <circle cx="8" cy="4.9" r=".35" fill="currentColor" />
      </>
    ),
  }[tone];
  return (
    <svg className="tone-icon" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="8" cy="8" r="6.6" strokeWidth="1.4" />
      {path}
    </svg>
  );
}

export function StatusChip({ status }: { status: string | null | undefined }) {
  const { code } = useI18n();
  if (!status) return null;
  const tone = toneOf(status);
  return (
    <span className={`pill tone-${tone}`}>
      <ToneIcon tone={tone} />
      {code("status", status)}
    </span>
  );
}
