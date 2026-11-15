import { memo, useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ClaimKind, TraceStep } from "@alphaforge/api-client";
import { parseCiteHref, splitSummary, tagsToLinks } from "./cite";
import { stepList } from "./format";
import { useI18n } from "./i18n";

/** Claim chip: "Fact · step 5". Facts open the trace at the cited steps. */
export function CiteChip({
  kind,
  steps,
  onCite,
}: {
  kind: ClaimKind;
  steps: number[];
  onCite?: (steps: number[]) => void;
}) {
  const { t, code } = useI18n();
  const where = steps.length ? t(steps.length === 1 ? "cite.step" : "cite.steps", { n: stepList(steps) }) : "";
  const label = where ? `${code("claim", kind)} · ${where}` : code("claim", kind);
  if (!steps.length || !onCite) {
    return <span className={`chip chip-${kind}`}>{label}</span>;
  }
  return (
    <button type="button" className={`chip chip-${kind}`} onClick={() => onCite(steps)} title={t("tr.open")}>
      {label}
    </button>
  );
}

/**
 * Assistant answer. When it starts with a summary ("## Summary" / "## Résumé"), the summary is always shown and
 * the rest of the analysis sits behind a "Show full analysis" toggle (controlled by the chat, so the global
 * Simple / Detailed switch can set its default). Older answers without a summary are shown whole.
 */
export const Answer = memo(function Answer({
  content,
  trace,
  onCite,
  showFull,
  onToggleFull,
  id,
}: {
  content: string;
  trace: TraceStep[];
  onCite: (steps: number[]) => void;
  showFull: boolean;
  onToggleFull: () => void;
  id: string;
}) {
  const { t } = useI18n();
  const parts = useMemo(() => {
    const known = new Set(trace.map((s) => s.step));
    const split = splitSummary(content);
    return split
      ? { summary: tagsToLinks(split.summary, known), rest: split.rest ? tagsToLinks(split.rest, known) : "" }
      : { summary: tagsToLinks(content, known), rest: "" };
  }, [content, trace]);
  const restId = `full-${id}`;
  const components = useMemo<Components>(
    () => ({
      a({ href, children }) {
        const cite = parseCiteHref(href);
        if (cite) return <CiteChip kind={cite.kind} steps={cite.steps} onCite={onCite} />;
        return (
          <a href={href} target="_blank" rel="noreferrer noopener">
            {children}
          </a>
        );
      },
      table({ children }) {
        return (
          <div className="table-wrap">
            <table>{children}</table>
          </div>
        );
      },
    }),
    [onCite],
  );
  return (
    <div className="answer">
      <div className="answer-summary">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {parts.summary}
        </ReactMarkdown>
      </div>
      {parts.rest && (
        <>
          <button
            type="button"
            className="toggle"
            aria-expanded={showFull}
            aria-controls={restId}
            onClick={onToggleFull}
          >
            <span className="toggle-icon" aria-hidden="true">
              {showFull ? "▾" : "▸"}
            </span>
            {showFull ? t("ans.hideFull") : t("ans.showFull")}
          </button>
          {showFull && (
            <div className="answer-rest" id={restId}>
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
                {parts.rest}
              </ReactMarkdown>
            </div>
          )}
        </>
      )}
    </div>
  );
});
