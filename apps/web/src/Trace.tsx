import { useEffect, useRef } from "react";
import type { TraceStep } from "@alphaforge/api-client";
import { fmtTime } from "./format";
import { useI18n } from "./i18n";

const MAX_JSON = 6000;
const MAX_SUMMARY = 240;

function json(value: unknown): { text: string; truncated: boolean } {
  let text: string;
  try {
    text = JSON.stringify(value, null, 2) ?? "null";
  } catch {
    text = String(value);
  }
  return text.length > MAX_JSON ? { text: text.slice(0, MAX_JSON), truncated: true } : { text, truncated: false };
}

function StepData({ step }: { step: TraceStep }) {
  const { t } = useI18n();
  const input = json(step.input);
  const output = json(step.output);
  return (
    <details className="step-data">
      <summary>{t("tr.data")}</summary>
      <h5>{t("tr.input")}</h5>
      <pre>
        {input.text}
        {input.truncated && `\n${t("tr.truncated")}`}
      </pre>
      <h5>{t("tr.output")}</h5>
      <pre>
        {output.text}
        {output.truncated && `\n${t("tr.truncated")}`}
      </pre>
    </details>
  );
}

/**
 * Every step of the run (who did what, with which data). `focus` (a counter) scrolls to the first
 * highlighted step each time a claim chip is clicked.
 */
export function Trace({
  trace,
  open,
  onToggle,
  highlight,
  focus,
}: {
  trace: TraceStep[];
  open: boolean;
  onToggle: (open: boolean) => void;
  highlight: number[];
  focus: number;
}) {
  const { t, code, locale } = useI18n();
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    if (!open || !focus || !highlight.length) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-step="${Math.min(...highlight)}"]`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
    el?.focus({ preventScroll: true });
  }, [focus, open, highlight]);

  if (!trace.length) return null;
  const marked = new Set(highlight);
  return (
    <details className="panel trace" open={open} onToggle={(e) => onToggle(e.currentTarget.open)}>
      <summary>{t("sec.trace", { n: trace.length })}</summary>
      <ol ref={listRef} className="steps">
        {trace.map((s) => {
          const summary =
            s.outputSummary.length > MAX_SUMMARY ? `${s.outputSummary.slice(0, MAX_SUMMARY)}…` : s.outputSummary;
          return (
            <li
              key={s.step}
              data-step={s.step}
              tabIndex={-1}
              className={`step actor-${s.actor.split(":")[0]}${marked.has(s.step) ? " marked" : ""}`}
            >
              <span className="step-num">{s.step}</span>
              <div className="step-body">
                <div className="step-head">
                  <strong>{code("actor", s.actor)}</strong>
                  <code>{s.action}</code>
                  <time dateTime={s.timestamp}>{fmtTime(locale, s.timestamp)}</time>
                </div>
                {summary && <p className="step-summary">{summary}</p>}
                <StepData step={s} />
              </div>
            </li>
          );
        })}
      </ol>
    </details>
  );
}
