import { useEffect, useState } from "react";
import type { Persona, PersonaId } from "@alphaforge/api-client";
import { api } from "./api";
import { AppBar } from "./AppBar";
import { fmtLimit } from "./format";
import { useHealth } from "./health";
import { useI18n, type Key } from "./i18n";
import { PERSONAS } from "./personas";

export function PersonaPicker({ onPick }: { onPick: (id: PersonaId) => void }) {
  const { t, code, locale } = useI18n();
  const health = useHealth();
  // Limits come from personas.py through GET /personas. Without the backend the cards still work, without limits.
  const [loaded, setLoaded] = useState<Persona[] | null>(null);
  useEffect(() => {
    let live = true;
    api
      .GET("/personas")
      .then(({ data }) => live && data && setLoaded(data.items))
      .catch(() => undefined);
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
        <h1>{t("picker.title")}</h1>
        <p className="lead">{t("picker.lead")}</p>
        <div className="cards">
          {PERSONAS.map((fallback) => {
            const p = loaded?.find((x) => x.id === fallback.id);
            const limits = Object.entries(p?.limits ?? {});
            return (
              <button key={fallback.id} className="card" onClick={() => onPick(fallback.id)}>
                <span className="avatar" aria-hidden="true">
                  {fallback.name[0]}
                </span>
                <strong>{t("persona.nameAge", { name: p?.name ?? fallback.name, age: p?.age ?? fallback.age })}</strong>
                <span className="card-blurb">{t(`persona.${fallback.id}` as Key)}</span>
                {limits.length > 0 && (
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
                )}
                <span className="card-cta">
                  {t("picker.cta")} <span aria-hidden="true">→</span>
                </span>
              </button>
            );
          })}
        </div>
        {loaded && <p className="disclaimer">{t("picker.limitsNote")}</p>}
        <p className="disclaimer">{t("app.disclaimer")}</p>
      </main>
    </div>
  );
}
