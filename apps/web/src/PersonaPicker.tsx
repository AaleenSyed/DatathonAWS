import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { Persona, PersonaId } from "@alphaforge/api-client";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
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

/**
 * Persona selection. The three profiles are a radio group (arrow keys move the selection, Tab leaves the group);
 * the one primary action is "Start chat with <name>". The selected card shows a border, a check mark and the word
 * "Selected", so the state never depends on colour alone.
 */
export function PersonaPicker({ onPick, onBuild }: { onPick: (id: PersonaId) => void; onBuild: () => void }) {
  const { t, code, locale } = useI18n();
  const health = useHealth();
  // Limits come from personas.py through GET /personas. Without the backend the cards still work, without limits.
  const [loaded, setLoaded] = useState<Persona[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<PersonaId | null>(null);
  const radios = useRef<Record<string, HTMLButtonElement | null>>({});
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
  const chosen = PERSONAS.find((p) => p.id === selected);
  const chosenName = chosen ? (loaded?.find((x) => x.id === chosen.id)?.name ?? chosen.name) : "";

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = PERSONAS.length - 1;
    const to =
      e.key === "ArrowRight" || e.key === "ArrowDown" ? (index === last ? 0 : index + 1)
      : e.key === "ArrowLeft" || e.key === "ArrowUp" ? (index === 0 ? last : index - 1)
      : e.key === "Home" ? 0
      : e.key === "End" ? last
      : -1;
    if (to < 0) return;
    e.preventDefault();
    const next = PERSONAS[to].id;
    setSelected(next);
    radios.current[next]?.focus();
  }

  return (
    <div className="page">
      <AppBar />
      <main id="main" tabIndex={-1} className="picker">
        {health?.agentMode === "demo" && (
          <p className="banner" role="status">
            {t("app.demo")}
          </p>
        )}
        <p className="eyebrow">{t("picker.step")}</p>
        <h1 id="picker-title">{withEmphasis(t("picker.title"))}</h1>
        <p className="lead">{t("picker.lead")}</p>

        <div
          role="radiogroup"
          aria-labelledby="picker-title"
          className="mt-8 grid grid-cols-[repeat(auto-fit,minmax(min(17rem,100%),1fr))] gap-4"
        >
          {PERSONAS.map((fallback, i) => {
            const p = loaded?.find((x) => x.id === fallback.id);
            const limits = Object.entries(p?.limits ?? {});
            const risk = p?.riskTolerance ?? FALLBACK[fallback.id].risk;
            const horizon = (p?.horizonYears ?? FALLBACK[fallback.id].horizon).replace("-", "–");
            const isSelected = selected === fallback.id;
            const name = p?.name ?? fallback.name;
            return (
              <button
                key={fallback.id}
                ref={(el) => {
                  radios.current[fallback.id] = el;
                }}
                type="button"
                role="radio"
                aria-checked={isSelected}
                aria-labelledby={`persona-${fallback.id}-title`}
                aria-describedby={`persona-${fallback.id}-blurb`}
                // Roving tabindex: one stop in the group (the selected card, else the first).
                tabIndex={isSelected || (!selected && i === 0) ? 0 : -1}
                onClick={() => setSelected(fallback.id)}
                onKeyDown={(e) => onKeyDown(e, i)}
                className={cn(
                  "relative flex cursor-pointer flex-col gap-4 rounded-[var(--radius)] border-2 bg-card p-5 text-left",
                  "text-body shadow-sm transition-[transform,border-color,box-shadow,background-color] duration-200",
                  "motion-safe:hover:-translate-y-0.5 hover:shadow-lg",
                  isSelected ? "border-primary bg-accent shadow-md" : "border-border hover:border-input",
                )}
              >
                {isSelected && (
                  <span
                    className="absolute right-4 top-4 inline-flex items-center gap-1.5 rounded-full bg-primary px-2.5 py-1 text-xs font-semibold text-primary-foreground"
                  >
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="3"
                      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M5 12.5l4.5 4.5L19 7.5" />
                    </svg>
                    {t("picker.selected")}
                  </span>
                )}
                <span className="flex items-center gap-3 pr-0">
                  <span className={`avatar avatar-${fallback.id}`} aria-hidden="true">
                    {fallback.name[0]}
                  </span>
                  <span className={cn("grid min-w-0 gap-0.5", isSelected && "pt-7 sm:pt-0")}>
                    <strong id={`persona-${fallback.id}-title`} className="text-[1.2rem] font-semibold leading-tight">
                      {t("persona.nameAge", { name, age: p?.age ?? fallback.age })}
                    </strong>
                    <span className="text-[0.95rem] leading-snug">{t(`goal.${fallback.id}` as Key)}</span>
                  </span>
                </span>
                <span className="flex flex-wrap gap-1.5">
                  {[t(`tag.risk.${risk}` as Key), t("tag.horizon", { h: horizon }), t(`tag.pref.${fallback.id}` as Key)].map(
                    (tag) => (
                      <span key={tag} className="rounded-full border border-border bg-card px-2.5 py-0.5 text-[0.8rem] font-medium">
                        {tag}
                      </span>
                    ),
                  )}
                </span>
                <span id={`persona-${fallback.id}-blurb`} className="flex-1 text-[0.95rem] text-muted-foreground">
                  {t(`persona.${fallback.id}` as Key)}
                </span>
                {limits.length > 0 ? (
                  <span className="grid min-w-0 gap-1 rounded-xl bg-muted px-3.5 py-3 text-[0.875rem]">
                    <span className="text-xs font-semibold uppercase tracking-[.08em] text-muted-foreground">
                      {t("picker.limits")}
                    </span>
                    {limits.map(([rule, value]) => (
                      <LimitRow key={rule} label={code("rule", rule)} value={fmtLimit(locale, rule, value, sector, "—")} />
                    ))}
                    {p && p.esgReviewTickers.length > 0 && (
                      <LimitRow label={code("rule", "esg_review")} value={p.esgReviewTickers.join(", ")} />
                    )}
                  </span>
                ) : (
                  !failed && (
                    <span className="grid gap-2 rounded-xl bg-muted px-3.5 py-3.5" role="status">
                      <span className="sr-only">{t("loading")}</span>
                      {["40%", "90%", "75%"].map((w) => (
                        <span
                          key={w}
                          aria-hidden="true"
                          className="h-2.5 rounded-full bg-border motion-safe:animate-pulse"
                          style={{ width: w }}
                        />
                      ))}
                    </span>
                  )
                )}
              </button>
            );
          })}
        </div>

        {/* The one primary action of the page. */}
        <div className="mt-8 flex flex-col items-center gap-2">
          <button
            type="button"
            aria-disabled={!selected}
            onClick={() => selected && onPick(selected)}
            className={buttonVariants({
              size: "lg",
              variant: selected ? "default" : "secondary",
              className: cn("w-full sm:w-auto sm:min-w-72", !selected && "cursor-not-allowed text-muted-foreground"),
            })}
          >
            {selected ? t("picker.startWith", { name: chosenName }) : t("picker.choose")}
            {selected && <span aria-hidden="true">→</span>}
          </button>
        </div>

        <section className="mt-10" aria-labelledby="build-heading">
          <h2
            id="build-heading"
            className={cn(
              "mb-3 flex items-center gap-3 font-sans text-sm font-semibold text-muted-foreground",
              "after:h-px after:flex-1 after:bg-border",
            )}
          >
            {t("pf.barHeading")}
          </h2>
          {/* Secondary to the three profiles: one compact row */}
          <div
            className={cn(
              "flex flex-wrap items-center gap-4 rounded-[var(--radius)] border border-dashed border-input",
              "bg-card px-4 py-4 sm:flex-nowrap sm:px-5",
            )}
          >
            <span className="avatar font-sans text-2xl font-normal" aria-hidden="true">
              +
            </span>
            <span className="grid min-w-0 flex-1 basis-48 gap-0.5">
              <strong className="text-[1.1rem] font-semibold leading-tight">{t("pf.cardTitle")}</strong>
              <span className="text-[0.95rem] text-muted-foreground">{t("pf.barSub")}</span>
            </span>
            <button
              type="button"
              onClick={onBuild}
              className={buttonVariants({ variant: "outline", className: "w-full sm:w-auto" })}
            >
              {t("pf.cardCta")} <span aria-hidden="true">→</span>
            </button>
          </div>
        </section>
        {loaded && <p className="mt-6 text-center text-sm text-muted-foreground">{t("picker.limitsNote")}</p>}
      </main>
      <Footer />
    </div>
  );
}

function LimitRow({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex justify-between gap-3">
      <span className="min-w-0 sm:whitespace-nowrap">{label}</span>
      <span className="text-right font-semibold text-foreground tabular-nums">{value}</span>
    </span>
  );
}
