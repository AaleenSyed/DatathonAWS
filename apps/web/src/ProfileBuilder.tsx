import { useEffect, useRef, useState } from "react";
import type { Persona, ProfileAnswers } from "@alphaforge/api-client";
import { api } from "./api";
import { AppBar, Footer } from "./AppBar";
import { fmtLimit } from "./format";
import { useHealth } from "./health";
import { useI18n, type Key } from "./i18n";

// "Build my own profile": 7 multiple-choice questions (no name, age or amounts). The backend
// (POST /profiles, profile_builder.py, no LLM) turns them into a fictional profile with limits and the reason
// for each limit; the chat then uses it like a built-in persona (personaId "custom-<8 chars>").

type Single = Exclude<keyof ProfileAnswers, "industries">;

const QUESTIONS: { id: Single; options: string[] }[] = [
  { id: "goal", options: ["preserve", "income", "balanced", "growth"] },
  { id: "horizon", options: ["lt3", "3to5", "5to10", "10plus"] },
  { id: "drop25", options: ["sell_all", "sell_some", "hold", "buy_more"] },
  { id: "liquidity", options: ["high", "some", "low", "none"] },
  { id: "crypto", options: ["none", "small", "significant"] },
  { id: "esg", options: ["not_important", "prefer", "strict"] },
];
// The industry sector groups of the universe (server: profile_builder.industries()).
export const INDUSTRIES = [
  "Information Technology", "Financials", "Energy", "Consumer Staples", "Consumer Discretionary",
  "Health Care", "Industrials", "Utilities", "Communication Services",
];
const STORE = "customProfileAnswers";

function loadAnswers(): Partial<ProfileAnswers> {
  try {
    return JSON.parse(sessionStorage.getItem(STORE) ?? "{}") as Partial<ProfileAnswers>;
  } catch {
    return {};
  }
}

/** Monochrome spark (same mark as the logo): the avatar of a custom profile. */
export function SparkAvatar({ large = false }: { large?: boolean }) {
  return (
    <span className={`avatar${large ? " avatar-lg" : ""}`} aria-hidden="true">
      <svg viewBox="0 0 32 32" width={large ? 28 : 22} height={large ? 28 : 22}>
        <path d="M16 5c.8 5.4 3.6 8.2 9 9-5.4.8-8.2 3.6-9 9-.8-5.4-3.6-8.2-9-9 5.4-.8 8.2-3.6 9-9z" fill="currentColor" />
      </svg>
    </span>
  );
}

/** The custom profile: risk level, horizon, goal, every limit with the reason and the questions behind it. */
export function ProfileCard({ p, compact = false }: { p: Persona; compact?: boolean }) {
  const { t, code, locale } = useI18n();
  const reasons = p.limitReasons ?? {};
  const rows = [
    ...Object.entries(p.limits).map(([rule, value]) => ({ rule, value: fmtLimit(locale, rule, value, (n) => code("sector", n), "—") })),
    ...(p.esgReviewTickers.length ? [{ rule: "esg_review", value: p.esgReviewTickers.join(", ") }] : []),
  ];
  return (
    <section className={`profile-card${compact ? " compact" : ""}`} aria-labelledby={`pc-${p.id}`}>
      <header>
        <SparkAvatar />
        <div>
          <h2 id={`pc-${p.id}`}>{t("pf.yourProfile")}</h2>
          <div className="tags">
            <span className="tag-pill strong">{t(`tag.risk.${p.riskTolerance}` as Key)}</span>
            <span className="tag-pill">{t("tag.horizon", { h: p.horizonYears.replace("-", "–") })}</span>
            <span className="tag-pill">{code("goal", p.goal)}</span>
          </div>
        </div>
      </header>
      <h3 className="pf-sub">{t("pf.limitsTitle")}</h3>
      <ul className="pf-limits">
        {rows.map((r) => (
          <li key={r.rule}>
            <div className="pf-limit-head">
              <span>{code("rule", r.rule)}</span>
              <strong className="num">{r.value}</strong>
            </div>
            {reasons[r.rule] && (
              <p className="pf-reason">
                {reasons[r.rule].text}
                <span className="pf-qs">
                  {reasons[r.rule].questions.map((q) => (
                    <span key={q} className="chip">{t("pf.q", { n: q })}</span>
                  ))}
                </span>
              </p>
            )}
          </li>
        ))}
      </ul>
      <p className="note">{t("pf.note")}</p>
    </section>
  );
}

export function ProfileBuilder({ onStart, onBack }: { onStart: (id: string) => void; onBack: () => void }) {
  const { t, code, lang } = useI18n();
  const health = useHealth();
  const [answers, setAnswers] = useState<Partial<ProfileAnswers>>(loadAnswers);
  const [profile, setProfile] = useState<Persona | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const industries = answers.industries ?? [];
  const done = QUESTIONS.filter((q) => answers[q.id]).length;
  const complete = done === QUESTIONS.length;

  useEffect(() => {
    try {
      sessionStorage.setItem(STORE, JSON.stringify(answers));
    } catch {
      /* storage unavailable */
    }
  }, [answers]);

  async function submit() {
    if (!complete || busy) return;
    setBusy(true);
    setError(null);
    const { data, error: err } = await api.POST("/profiles", {
      body: { answers: { ...answers, industries } as ProfileAnswers, language: lang },
    });
    setBusy(false);
    if (err || !data) return setError(err?.message ?? t("pf.err"));
    setProfile(data);
    requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  // The reasons are written in the language of the request: rebuild when the language changes.
  const shownLang = useRef(lang);
  useEffect(() => {
    if (profile && shownLang.current !== lang) void submit();
    shownLang.current = lang;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang]);

  function pick(q: Single, value: string) {
    setAnswers((a) => ({ ...a, [q]: value }));
    setProfile(null);
  }

  function toggle(industry: string) {
    setAnswers((a) => {
      const cur = a.industries ?? [];
      return { ...a, industries: cur.includes(industry) ? cur.filter((x) => x !== industry) : [...cur, industry] };
    });
    setProfile(null);
  }

  return (
    <div className="page">
      <AppBar
        left={
          <button className="back" onClick={onBack}>
            <span aria-hidden="true">←</span> {t("pf.back")}
          </button>
        }
      />
      {health?.agentMode === "demo" && <p className="banner">{t("app.demo")}</p>}
      <main id="main" tabIndex={-1} className="picker builder">
        <p className="eyebrow">{t("pf.eyebrow")}</p>
        <h1>{t("pf.title")}</h1>
        <p className="lead">{t("pf.lead")}</p>
        <p className="privacy">{t("pf.privacy")}</p>

        <form className="questions" onSubmit={(e) => (e.preventDefault(), void submit())}>
          {QUESTIONS.map((q, i) => (
            <fieldset key={q.id} className="question">
              <legend>
                <span className="q-num">{i + 1}</span>
                {t(`pf.${q.id}.q` as Key)}
              </legend>
              <div className="options" role="radiogroup">
                {q.options.map((o) => (
                  <label key={o} className={`option${answers[q.id] === o ? " selected" : ""}`}>
                    <input
                      type="radio"
                      name={q.id}
                      value={o}
                      checked={answers[q.id] === o}
                      onChange={() => pick(q.id, o)}
                    />
                    {t(`pf.${q.id}.${o}` as Key)}
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
          <fieldset className="question">
            <legend>
              <span className="q-num">7</span>
              {t("pf.industries.q")} <span className="muted">{t("pf.optional")}</span>
            </legend>
            <div className="options">
              {INDUSTRIES.map((s) => (
                <label key={s} className={`option${industries.includes(s) ? " selected" : ""}`}>
                  <input type="checkbox" checked={industries.includes(s)} onChange={() => toggle(s)} />
                  {code("sector", s)}
                </label>
              ))}
            </div>
          </fieldset>

          <div className="builder-actions">
            <span className="muted">{t("pf.progress", { n: done, total: QUESTIONS.length })}</span>
            <button type="submit" className="btn btn-primary" disabled={!complete || busy}>
              {busy ? t("loading") : profile ? t("pf.rebuild") : t("pf.build")}
            </button>
          </div>
          {error && (
            <p className="error" role="alert">
              ⚠ {error}
            </p>
          )}
        </form>

        {profile && (
          <div ref={resultRef} className="builder-result">
            <ProfileCard p={profile} />
            <button type="button" className="btn btn-primary" onClick={() => onStart(profile.id)}>
              {t("pf.start")} <span aria-hidden="true">→</span>
            </button>
          </div>
        )}
      </main>
      <Footer />
    </div>
  );
}
