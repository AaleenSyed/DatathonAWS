import { memo, useMemo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ClaimKind, ExplainerPayload, TraceStep } from "@alphaforge/api-client";
import { parseCiteHref, splitSummary, tagsToLinks } from "./cite";
import { stepList } from "./format";
import { useI18n } from "./i18n";
import { ToneIcon, type Tone } from "./Status";
import { StockCards } from "./StockCards";
import { boldMentions, boldTerms, mentionedStocks } from "./stocks";

const CURSOR = " [▍](#cursor)"; // rendered as a blinking cursor at the end of the streamed text

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
 * Assistant answer. The summary is shown as a hero card whose left border follows the answer's overall
 * suitability tone (pass / caution / conflict; neutral while streaming). When it starts with a summary ("## Summary" / "## Résumé"), the summary is always shown and
 * the rest of the analysis sits behind a "Show full analysis" toggle (controlled by the chat, so the global
 * Simple / Detailed switch can set its default). Older answers without a summary are shown whole.
 * Tickers, company and sector names from the trace are bolded in the summary; once the answer is complete, one
 * stock card per mentioned equity sits under the summary (numbers from the trace only).
 */
export const Answer = memo(function Answer({
  content,
  trace,
  onCite,
  showFull,
  onToggleFull,
  id,
  tone,
  streaming,
  afterSummary,
  final,
  hideStatus = false,
}: {
  /** Explainer payload (names of the analyzed targets, for bolding and stock cards). */
  final?: ExplainerPayload | null;
  /** The profile check above the answer already says it: hide the summary card's own status line. */
  hideStatus?: boolean;
  /** Shown right under the summary card, before "Show full analysis" (the recommended sector cards). */
  afterSummary?: ReactNode;
  content: string;
  trace: TraceStep[];
  onCite: (steps: number[]) => void;
  showFull: boolean;
  onToggleFull: () => void;
  id: string;
  tone: Tone;
  streaming: boolean;
}) {
  const { t } = useI18n();
  const parts = useMemo(() => {
    const known = new Set(trace.map((s) => s.step));
    const terms = boldTerms(trace, final);
    const split = splitSummary(content);
    const p = split
      ? {
          summary: boldMentions(tagsToLinks(split.summary, known), terms),
          rest: split.rest ? tagsToLinks(split.rest, known) : "",
        }
      : { summary: boldMentions(tagsToLinks(content, known), terms), rest: "" };
    if (streaming) {
      if (p.rest && showFull) p.rest += CURSOR;
      else p.summary += CURSOR;
    }
    return p;
  }, [content, trace, final, streaming, showFull]);
  // Cards only once the text is complete, so they do not jump in while it streams.
  const stocks = useMemo(
    () => (streaming ? [] : mentionedStocks(content, trace, final)),
    [content, trace, final, streaming],
  );
  const restId = `full-${id}`;
  const components = useMemo<Components>(
    () => ({
      a({ href, children }) {
        if (href === "#cursor") return <span className="cursor" aria-hidden="true" />;
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
      <div className={`answer-summary hero tone-${tone}`}>
        {!hideStatus && tone !== "neutral" && tone !== "info" && (
          <p className={`hero-status tone-${tone}`}>
            <ToneIcon tone={tone} />
            {t(`hero.${tone === "caution" ? "flag" : tone}`)}
          </p>
        )}
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {parts.summary}
        </ReactMarkdown>
      </div>
      <StockCards stocks={stocks} onCite={onCite} />
      {afterSummary}
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
