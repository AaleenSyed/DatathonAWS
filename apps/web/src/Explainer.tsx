import { memo, type ReactNode } from "react";
import type {
  ExplainerPayload,
  MarketContext,
  Review,
  RiskRow,
  SuitabilityResult,
  TargetSummary,
} from "@alphaforge/api-client";
import { CiteChip } from "./Answer";
import { fmtDate, fmtLimit, num, pct, stepList } from "./format";
import { sourceParts } from "./cite";
import { useI18n, type Key } from "./i18n";

type OnCite = (steps: number[]) => void;

const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

function Badge({ kind, value }: { kind: "status" | "risk"; value: string | null | undefined }) {
  const { code } = useI18n();
  if (!value) return null;
  const cls = kind === "status" ? `st st-${value}` : `risk risk-${value.toLowerCase().replace(/\s+/g, "-")}`;
  return <span className={cls}>{code(kind, value)}</span>;
}

function Steps({ steps, onCite }: { steps: number[]; onCite: OnCite }) {
  return steps.length ? <CiteChip kind="fact" steps={steps} onCite={onCite} /> : null;
}

// ---------- Target cards ----------

function TargetCard({ s, onCite }: { s: TargetSummary; onCite: OnCite }) {
  const { t, code, locale } = useI18n();
  const metric = (label: string, value: number | null, key: "annualizedVol" | "maxDrawdown" | "totalReturn") => {
    const r = s.range?.[key];
    return (
      <div className="metric">
        <dt>{label}</dt>
        <dd>
          {r
            ? t("m.range", { min: pct(locale, r.min), minT: r.minTicker, max: pct(locale, r.max), maxT: r.maxTicker })
            : pct(locale, value)}
        </dd>
      </div>
    );
  };
  return (
    <article className={`target-card overall-${s.suitabilityOverall ?? "none"}`}>
      <header>
        <div>
          <h5>{code("sector", s.name)}</h5>
          <span className="muted">{code("kind", s.kind)}</span>
        </div>
        <Badge kind="status" value={s.suitabilityOverall} />
      </header>
      <dl className="metrics">
        {s.riskLabel && (
          <div className="metric">
            <dt>{t("m.risk")}</dt>
            <dd>
              <Badge kind="risk" value={s.riskLabel} />
            </dd>
          </div>
        )}
        {metric(t("m.vol"), s.annualizedVol, "annualizedVol")}
        {metric(t("m.mdd"), s.maxDrawdown, "maxDrawdown")}
        {metric(t("m.ret"), s.totalReturn, "totalReturn")}
        {isNum(s.momentum12m) && (
          <div className="metric">
            <dt>{t("m.mom")}</dt>
            <dd>
              {pct(locale, s.momentum12m)}
              {s.trend && <span className="muted">, {code("trend", s.trend)}</span>}
            </dd>
          </div>
        )}
      </dl>
      {s.range && <p className="note">{t("m.noBlend")}</p>}
      {s.members.length > 0 && (
        <p className="members">
          <span className="muted">
            {t("m.members")}
            {t("colon")}{" "}
          </span>
          {s.members.map((m, i) => (
            <span key={m.ticker}>
              {i > 0 && ", "}
              <abbr title={m.name}>{m.ticker}</abbr>
            </span>
          ))}
        </p>
      )}
      <footer>
        {s.period && (
          <span className="muted">
            {t("m.period", {
              start: fmtDate(locale, s.period.start),
              end: fmtDate(locale, s.period.end),
              ccy: s.currency ?? "—",
            })}
          </span>
        )}
        <Steps steps={s.traceSteps} onCite={onCite} />
      </footer>
    </article>
  );
}

// ---------- Risk charts ----------

interface Bar {
  key: string;
  label: string;
  group: string | null;
  value: number;
  steps: number[];
}

function BarChart({
  title,
  bars,
  limit,
  limitLabel,
  over,
  onCite,
}: {
  title: string;
  bars: Bar[];
  limit: number | null;
  limitLabel: string;
  over: (v: number) => boolean;
  onCite: OnCite;
}) {
  const { t, locale } = useI18n();
  const scale = Math.max(...bars.map((b) => Math.abs(b.value)), limit != null ? Math.abs(limit) : 0) * 1.08 || 1;
  const pos = (v: number) => `${(Math.abs(v) / scale) * 100}%`;
  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <div className="chart-rows">
        {bars.map((b) => {
          const isOver = limit != null && over(b.value);
          const state = limit == null ? "" : isOver ? t("chart.over") : t("chart.within");
          return (
            <div className="chart-row" key={b.key}>
              <div className="chart-label">
                <span>{b.label}</span>
                {b.group && <small>{b.group}</small>}
              </div>
              <div
                className="chart-track"
                title={t(b.steps.length === 1 ? "cite.step" : "cite.steps", { n: stepList(b.steps) })}
              >
                <div className={`chart-bar${limit == null ? "" : isOver ? " over" : " within"}`} style={{ width: pos(b.value) }} />
                {limit != null && <div className="chart-limit" style={{ left: pos(limit) }} aria-hidden="true" />}
              </div>
              <button
                type="button"
                className="chart-value"
                onClick={() => onCite(b.steps)}
                aria-label={`${b.label}: ${pct(locale, b.value)}${state ? `, ${state}` : ""}. ${t("tr.open")}`}
              >
                {pct(locale, b.value)}
              </button>
            </div>
          );
        })}
      </div>
      <p className="chart-legend">
        {limit != null && <span className="legend-limit" aria-hidden="true" />}
        {limitLabel}
      </p>
    </figure>
  );
}

function RiskCharts({ f, onCite }: { f: ExplainerPayload; onCite: OnCite }) {
  const { t, code, locale } = useI18n();
  const name = f.persona.name;
  const volMax = isNum(f.personaLimits.vol_max) ? f.personaLimits.vol_max : null;
  const ddMax = isNum(f.personaLimits.stress_2022_max_drawdown) ? f.personaLimits.stress_2022_max_drawdown : null;
  const period = [...f.requestedTargets, ...f.recommendedSectors].find((s) => s.period)?.period;
  const toBar = (r: RiskRow, value: number): Bar => ({
    key: `${r.group}|${r.name}`,
    label: code("sector", r.name),
    group: r.group !== r.name ? code("sector", r.group) : null,
    value,
    steps: r.traceSteps,
  });
  const vol = f.riskTable.filter((r) => isNum(r.annualizedVol)).map((r) => toBar(r, r.annualizedVol!));
  const dd = f.riskTable.filter((r) => isNum(r.stress2022MaxDrawdown)).map((r) => toBar(r, r.stress2022MaxDrawdown!));
  if (!vol.length && !dd.length) return null;
  return (
    <details className="panel" open>
      <summary>{t("sec.charts")}</summary>
      {vol.length > 0 && (
        <BarChart
          title={
            period
              ? t("chart.vol", { start: fmtDate(locale, period.start), end: fmtDate(locale, period.end) })
              : t("m.vol")
          }
          bars={vol}
          limit={volMax}
          limitLabel={volMax != null ? t("chart.volLimit", { name, limit: pct(locale, volMax) }) : t("chart.noLimit", { name })}
          over={(v) => volMax != null && v > volMax}
          onCite={onCite}
        />
      )}
      {dd.length > 0 ? (
        <BarChart
          title={t("chart.dd")}
          bars={dd}
          limit={ddMax}
          limitLabel={ddMax != null ? t("chart.ddLimit", { name, limit: pct(locale, ddMax) }) : t("chart.noLimit", { name })}
          over={(v) => ddMax != null && v < ddMax}
          onCite={onCite}
        />
      ) : (
        <p className="note">{t("chart.noData")}</p>
      )}
      <p className="note">{t("chart.note")}</p>
    </details>
  );
}

// ---------- Profile check ----------

function Suitability({ results, onCite }: { results: SuitabilityResult[]; onCite: OnCite }) {
  const { t, code, locale } = useI18n();
  if (!results.length) return null;
  const sector = (n: string) => code("sector", n);
  const note = t("t.explanationsEn");
  return (
    <details className="panel" open>
      <summary>{t("sec.profile")}</summary>
      {note && <p className="note">{note}</p>}
      {results.map((r) => (
        <section key={`${r.target}|${r.traceStep}`} className="suit">
          <header>
            <h5>{code("sector", r.target)}</h5>
            <span className="muted">
              {code("kind", r.targetKind)} ·{" "}
              {r.proposedWeight != null ? t("t.weight", { w: pct(locale, r.proposedWeight) }) : t("t.noWeight")}
            </span>
            <span className="suit-overall">
              {t("t.overall")} <Badge kind="status" value={r.overall} />
            </span>
            <Steps steps={[r.traceStep]} onCite={onCite} />
          </header>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">{t("t.rule")}</th>
                  <th scope="col">{t("t.limit")}</th>
                  <th scope="col">{t("t.value")}</th>
                  <th scope="col">{t("t.status")}</th>
                </tr>
              </thead>
              <tbody>
                {r.checks.map((c) => (
                  <tr key={c.rule} className={`row-${c.status}`}>
                    <th scope="row">
                      {code("rule", c.rule)}
                      {c.explanation && <small lang="en">{c.explanation}</small>}
                    </th>
                    <td data-label={t("t.limit")}>{fmtLimit(locale, c.rule, c.limit, sector, "—")}</td>
                    <td data-label={t("t.value")}>{fmtLimit(locale, c.rule, c.value, sector, "—")}</td>
                    <td data-label={t("t.status")}>
                      <Badge kind="status" value={c.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </details>
  );
}

// ---------- Market context ----------

function Market({ m, onCite }: { m: MarketContext; onCite: OnCite }) {
  const { t, code, locale } = useI18n();
  return (
    <details className="panel">
      <summary>{t("sec.market")}</summary>
      <dl className="facts">
        <div>
          <dt>{t("mk.phase")}</dt>
          <dd>{code("phase", m.phase)}</dd>
        </div>
        {m.ruleFired && (
          <div>
            <dt>{t("mk.rule")}</dt>
            <dd lang="en">{m.ruleFired}</dd>
          </div>
        )}
        {m.sectorTilt.length > 0 && (
          <div>
            <dt>{t("mk.tilt")}</dt>
            <dd>{m.sectorTilt.map((s) => code("sector", s)).join(", ")}</dd>
          </div>
        )}
        <div>
          <dt>{t("mk.vix")}</dt>
          <dd>
            {num(locale, m.vix)}
            {m.mood && (
              <span className="muted">
                {" "}
                ({t("mk.mood")}
                {t("colon")} {code("mood", m.mood)})
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt>{t("mk.credit")}</dt>
          <dd>{m.creditSpreadRising == null ? "—" : m.creditSpreadRising ? t("mk.rising") : t("mk.notRising")}</dd>
        </div>
        <div>
          <dt>{t("mk.sentiment")}</dt>
          <dd>{num(locale, m.consumerSentiment)}</dd>
        </div>
      </dl>
      <p className="note">
        {t("mk.note", { date: fmtDate(locale, m.asOf) })} <Steps steps={m.traceSteps} onCite={onCite} />
      </p>
    </details>
  );
}

// ---------- Review ----------

function ReviewView({ r }: { r: Review }) {
  const { t } = useI18n();
  const row = (label: string, v: Review["work"], retries: number) => (
    <li>
      <span className={`st st-${v.verdict === "pass" ? "pass" : "conflict"}`}>
        {v.verdict === "pass" ? t("rv.pass") : t("rv.fail")}
      </span>{" "}
      {label}
      {retries > 0 && <span className="muted"> · {t("rv.retries", { n: retries })}</span>}
      {v.reasons.length > 0 && (
        <ul lang="en">
          {v.reasons.map((x, i) => (
            <li key={i}>{x}</li>
          ))}
        </ul>
      )}
    </li>
  );
  return (
    <details className="panel">
      <summary>{t("sec.review")}</summary>
      {r.incomplete && <p className="warn">{t("rv.incomplete")}</p>}
      <ul className="plain">
        {row(t("rv.work"), r.work, r.workRetries)}
        {row(t("rv.answer"), r.answer, r.answerRetries)}
      </ul>
    </details>
  );
}

// ---------- Claims ----------

/** "Yahoo Finance · 2021–2026 · CAD"; the full source text is in the tooltip. */
function SourceLabel({ source }: { source: string }) {
  const { t } = useI18n();
  const { providers, years, currency } = sourceParts(source);
  const names = providers.map((p) => (p.startsWith("src.") ? t(p as Key) : p));
  const label = [names.join(" + ") || t("src.other"), years, currency].filter(Boolean).join(" · ");
  return (
    <span className="source-label" title={source} tabIndex={0}>
      {label}
    </span>
  );
}

function Claims({ f, onCite }: { f: ExplainerPayload; onCite: OnCite }) {
  const { t } = useI18n();
  if (!f.claims.length) return null;
  return (
    <details className="panel">
      <summary>{t("sec.claims", { n: f.claims.length })}</summary>
      <ul className="claims">
        {f.claims.map((c, i) => (
          <li key={i}>
            <CiteChip kind={c.kind} steps={c.traceSteps} onCite={onCite} /> <span>{c.text}</span>
            {c.sources.length > 0 && (
              <span className="sources">
                {[...new Set(c.sources)].map((s, j) => (
                  <SourceLabel key={j} source={s} />
                ))}
              </span>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

// ---------- Panels ----------

function TargetGrid({ items, onCite }: { items: TargetSummary[]; onCite: OnCite }) {
  return (
    <div className="target-grid">
      {items.map((s) => (
        <TargetCard key={s.name} s={s} onCite={onCite} />
      ))}
    </div>
  );
}

/** Recommended sector cards: always shown next to the summary. */
export const Recommended = memo(function Recommended({ f, onCite }: { f: ExplainerPayload; onCite: OnCite }) {
  const { t } = useI18n();
  if (!f.recommendedSectors.length) return null;
  return (
    <section className="explainer recommended">
      <h4>{t("sec.recommended")}</h4>
      <TargetGrid items={f.recommendedSectors} onCite={onCite} />
    </section>
  );
});

/**
 * Everything behind "Show the evidence": other targets, conflicts, risk charts, profile check, market context,
 * claims, review, limitations, raw worker warnings, run info, and the trace (`children`).
 */
export const Evidence = memo(function Evidence({
  f,
  onCite,
  children,
}: {
  f: ExplainerPayload;
  onCite: OnCite;
  children?: ReactNode;
}) {
  const { t, code, locale } = useI18n();
  const shown = new Set(f.recommendedSectors.map((s) => s.name));
  const others = f.requestedTargets.filter((s) => !shown.has(s.name));
  return (
    <div className="explainer evidence">
      {others.length > 0 && (
        <section>
          <h4>{t("sec.requested")}</h4>
          <TargetGrid items={others} onCite={onCite} />
        </section>
      )}
      {f.conflicts.length > 0 && (
        <section className="conflicts" role="note">
          <h4>{t("sec.conflicts")}</h4>
          <ul>
            {f.conflicts.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </section>
      )}

      <RiskCharts f={f} onCite={onCite} />
      <Suitability results={f.suitability} onCite={onCite} />
      {f.marketContext && <Market m={f.marketContext} onCite={onCite} />}
      <Claims f={f} onCite={onCite} />
      <ReviewView r={f.review} />

      <details className="panel">
        <summary>{t("sec.limits")}</summary>
        <ul>
          {f.caveats.map((c) => (
            <li key={c}>{code("caveat", c)}</li>
          ))}
        </ul>
      </details>
      {f.limitations.length > 0 && (
        <details className="panel">
          <summary>{t("sec.warnings", { n: f.limitations.length })}</summary>
          <p className="note">{t("lim.warnings")}</p>
          <ul lang="en">
            {f.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </details>
      )}

      {children}

      <p className="run-info">
        {t("run.info", { id: f.run.runId, date: fmtDate(locale, f.run.analysisDate) })}
        <br />
        {f.run.s3Uri ? t("run.s3", { uri: f.run.s3Uri }) : t("run.local")}
      </p>
    </div>
  );
});
