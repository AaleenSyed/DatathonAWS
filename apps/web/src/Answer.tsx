import { memo, useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ClaimKind, TraceStep } from "@alphaforge/api-client";
import { parseCiteHref, tagsToLinks } from "./cite";
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

/** Assistant answer: markdown with the presenter's claim tags shown as chips. */
export const Answer = memo(function Answer({
  content,
  trace,
  onCite,
}: {
  content: string;
  trace: TraceStep[];
  onCite: (steps: number[]) => void;
}) {
  const markdown = useMemo(() => tagsToLinks(content, new Set(trace.map((s) => s.step))), [content, trace]);
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
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
});
