import type { ExplainerPayload, SuitabilityResult, TraceStep } from "@alphaforge/api-client";
import { CiteChip } from "./Answer";
import { useI18n } from "./i18n";
import { StatusChip, ToneIcon, answerTone, toneOf } from "./Status";

type OnCite = (steps: number[]) => void;

/** "INPUT" / "OUTPUT" when the Bedrock Guardrail stopped this turn (trace step `input_blocked` / `output_blocked`). */
export function blockedBy(trace: TraceStep[]): "input" | "output" | null {
  const s = trace.find((x) => x.actor === "guardrail" && x.action.endsWith("_blocked"));
  return s ? (s.action.startsWith("output") ? "output" : "input") : null;
}

/** Rules that did not pass for one target, e.g. "Single-stock cap, Volatility limit". */
function failedRules(r: SuitabilityResult, code: (k: "rule", v: string) => string) {
  return r.checks.filter((c) => c.status === "conflict" || c.status === "flag").map((c) => ({
    rule: code("rule", c.rule),
    status: c.status,
  }));
}

/**
 * Top of every finished answer: the profile check (fits / flag / conflict, or blocked) and the sectors that fit
 * the profile's limits, before any detail. Everything here comes from the explainer payload or the trace.
 * Renders nothing for a turn without an analysis (`f` null, e.g. a short chat reply), unless it was blocked.
 */
export function Verdict({
  f,
  trace,
  name,
  onCite,
}: {
  f: ExplainerPayload | null | undefined;
  trace: TraceStep[];
  name: string;
  onCite: OnCite;
}) {
  const { t, code } = useI18n();
  const blocked = blockedBy(trace);
  if (blocked) {
    const step = trace.find((x) => x.actor === "guardrail" && x.action.endsWith("_blocked"))?.step;
    return (
      <section className="verdict tone-blocked" aria-label={t("v.label")}>
        <p className="verdict-status">
          <ToneIcon tone="conflict" />
          {t("v.blocked")}
        </p>
        <p className="verdict-text">{t(blocked === "input" ? "v.blockedInput" : "v.blockedOutput")}</p>
        {step != null && <CiteChip kind="fact" steps={[step]} onCite={onCite} />}
      </section>
    );
  }

  if (!f) return null;
  const tone = answerTone(f);
  const requested = new Set(f.requestedTargets.map((s) => s.name));
  const asked = f.suitability.filter((r) => requested.has(r.target));
  const checked = asked.length ? asked : f.suitability;
  const issues = checked.filter((r) => r.overall === "conflict" || r.overall === "flag" || r.overall === "incomplete");
  const label = { pass: "v.fits", caution: "v.flag", conflict: "v.conflict", info: "v.fits", neutral: "v.none" }[tone];

  return (
    <section className={`verdict tone-${tone}`} aria-label={t("v.label")}>
      <div className="verdict-row">
        <h3 className="section-label">{t("v.check")}</h3>
        <p className="verdict-status">
          <ToneIcon tone={tone} />
          {t(label as "v.fits", { name })}
        </p>
        {issues.length > 0 && (
          <ul className="verdict-issues">
            {issues.map((r) => (
              <li key={`${r.target}|${r.traceStep}`}>
                <strong>{code("sector", r.target)}</strong> <StatusChip status={r.overall} />
                <span className="verdict-rules">
                  {failedRules(r, code)
                    .map((x) => x.rule)
                    .join(" · ")}
                </span>
                <CiteChip kind="fact" steps={[r.traceStep]} onCite={onCite} />
              </li>
            ))}
          </ul>
        )}
      </div>
      {f.recommendedSectors.length > 0 && (
        <div className="verdict-row">
          <h3 className="section-label">{t(asked.some((r) => r.overall === "conflict") ? "v.instead" : "v.rec", { name })}</h3>
          <ul className="verdict-recs">
            {f.recommendedSectors.map((s) => (
              <li key={s.name} className={`rec tone-${toneOf(s.suitabilityOverall)}`}>
                <strong className="rec-name">{code("sector", s.name)}</strong>
                <span className="muted">{code("kind", s.kind)}</span>
                <StatusChip status={s.suitabilityOverall} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
