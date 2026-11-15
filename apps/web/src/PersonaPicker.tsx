import { useEffect, useState } from "react";
import type { Persona, PersonaId } from "@alphaforge/api-client";
import { api } from "./api";
import { AppBar, Footer } from "./AppBar";
import { fmtLimit } from "./format";
import { useHealth } from "./health";
import { useI18n, type Key } from "./i18n";
import { PERSONAS } from "./personas";

/** "Who is *investing* today?" -> the word between asterisks in italics. */
function withEmphasis(text: string) {
  return text.split(/\*([^*]+)\*/).map((part, i) => (i % 2 ? <em key={i}>{part}</em> : part));
}

// Risk and horizon come from GET /personas (personas.py); the fallbacks keep the cards complete without it.
const FALLBACK: Record<PersonaId, { risk: string; horizon: string }> = {
  amira: { risk: "high", horizon: "15+" },
  mateo: { risk: "moderate", horizon: "8-12" },
  robert: { risk: "low-moderate", horizon: "3-5" },
};

export function PersonaPicker({ onPick }: { onPick: (id: PersonaId) => void }) {
  const { t, code, locale } = useI18n();
  const health = useHealth();
  // Limits come from personas.py through GET /personas. Without the backend the cards still work, without limits.
  const [loaded, setLoaded] = useState<Persona[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    api
      .GET("/personas")
      .then(({ data }) => {
        if (!live) return;
        if (data) setLoaded(data.items);
        else setFailed(true);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, []);

  const sector = (n: string) => code("sector", n);
  return (
    <div className="page">
      <AppBar />
      {health?.agentMode === "demo" && <p className="banner">{t("app.demo")}</p>}
      <main className="picker">
        <p className="eyebrow">{t("picker.step")}</p>
        <h1>{withEmphasis(t("picker.title"))}</h1>
        <p className="lead">{t("picker.lead")}</p>
        <div className="cards">
          {PERSONAS.map((fallback) => {
            const p = loaded?.find((x) => x.id === fallback.id);
            const limits = Object.entries(p?.limits ?? {});
            const risk = p?.riskTolerance ?? FALLBACK[fallback.id].risk;
            const horizon = (p?.horizonYears ?? FALLBACK[fallback.id].horizon).replace("-", "–");
            return (
              <button key={fallback.id} className={`card card-${fallback.id}`} onClick={() => onPick(fallback.id)}>
                <span className="card-head">
                  <span className={`avatar avatar-${fallback.id}`} aria-hidden="true">
                    {fallback.name[0]}
                  </span>
                  <span className="card-title">
                    <strong>{t("persona.nameAge", { name: p?.name ?? fallback.name, age: p?.age ?? fallback.age })}</strong>
                    <span className="card-goal">{t(`goal.${fallback.id}` as Key)}</span>
                  </span>
                </span>
                <span className="tags">
                  <span className="tag-pill">{t(`tag.risk.${risk}` as Key)}</span>
                  <span className="tag-pill">{t("tag.horizon", { h: horizon })}</span>
                  <span className="tag-pill">{t(`tag.pref.${fallback.id}` as Key)}</span>
                </span>
                <span className="card-blurb">{t(`persona.${fallback.id}` as Key)}</span>
                {limits.length > 0 ? (
                  <span className="card-limits">
                    <span className="card-limits-title">{t("picker.limits")}</span>
                    {limits.map(([rule, value]) => (
                      <span key={rule} className="limit-row">
                        <span>{code("rule", rule)}</span>
                        <span>{fmtLimit(locale, rule, value, sector, "—")}</span>
                      </span>
                    ))}
                    {p && p.esgReviewTickers.length > 0 && (
                      <span className="limit-row">
                        <span>{code("rule", "esg_review")}</span>
                        <span>{p.esgReviewTickers.join(", ")}</span>
                      </span>
                    )}
                  </span>
                ) : (
                  !failed && (
                    <span className="card-limits skeleton" aria-label={t("loading")}>
                      <span style={{ width: "40%" }} />
                      <span style={{ width: "90%" }} />
                      <span style={{ width: "75%" }} />
                    </span>
                  )
                )}
                <span className="card-cta">
                  {t("picker.cta")} <span aria-hidden="true">→</span>
                </span>
              </button>
            );
          })}
        </div>
        {loaded && <p className="disclaimer">{t("picker.limitsNote")}</p>}
      </main>
      <Footer />
    </div>
  );
}
