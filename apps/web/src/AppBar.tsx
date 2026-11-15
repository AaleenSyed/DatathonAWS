import { useState, type ReactNode } from "react";
import { useI18n } from "./i18n";
import { useViewMode, type ViewMode } from "./view";

/** Original mark: a four-point spark over a rising line (no real brand's logo). */
export function Wordmark() {
  return (
    <span className="wordmark">
      <svg className="wordmark-mark" viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
        <rect width="32" height="32" rx="9" fill="currentColor" />
        <path d="M16 6.5c.7 4.6 2.9 6.8 7.5 7.5-4.6.7-6.8 2.9-7.5 7.5-.7-4.6-2.9-6.8-7.5-7.5 4.6-.7 6.8-2.9 7.5-7.5z"
          fill="var(--on-accent)" />
        <path d="M7.5 25.5h17" stroke="var(--on-accent)" strokeWidth="1.8" strokeLinecap="round" opacity=".7" />
      </svg>
      <span className="wordmark-text">
        AlphaForge <span className="wordmark-ai">AI</span>
      </span>
    </span>
  );
}

/** Footer on every page: simulation notice and data sources. */
export function Footer() {
  const { t } = useI18n();
  return <footer className="site-footer">{t("footer.text")}</footer>;
}

function ThemeToggle() {
  const { t } = useI18n();
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme ?? "light");
  const next = theme === "dark" ? "light" : "dark";
  const label = next === "dark" ? t("theme.toDark") : t("theme.toLight");
  return (
    <button
      type="button"
      className="icon-btn"
      aria-label={label}
      title={label}
      onClick={() => {
        document.documentElement.dataset.theme = next;
        try {
          localStorage.setItem("theme", next);
        } catch {
          /* storage unavailable: theme still applies for this visit */
        }
        setTheme(next);
      }}
    >
      {theme === "dark" ? (
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      )}
    </button>
  );
}

/** EN/FR switch. The UI changes at once; the next answer is written in the new language. */
function LanguageToggle() {
  const { t, lang, setLang } = useI18n();
  const label = t("lang.switchTo");
  return (
    <button
      type="button"
      className="icon-btn lang-btn"
      aria-label={label}
      title={label}
      lang={lang === "fr" ? "en" : "fr"}
      onClick={() => setLang(lang === "fr" ? "en" : "fr")}
    >
      {t("lang.short")}
    </button>
  );
}

/** Simple / Detailed: the default of "Show full analysis" and "Show the evidence" for every answer. */
function ViewToggle() {
  const { t } = useI18n();
  const { mode, setMode } = useViewMode();
  const options: { value: ViewMode; label: string; hint: string }[] = [
    { value: "simple", label: t("view.simple"), hint: t("view.simpleHint") },
    { value: "detailed", label: t("view.detailed"), hint: t("view.detailedHint") },
  ];
  return (
    <div className="segmented" role="group" aria-label={t("view.label")}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={mode === o.value}
          title={o.hint}
          onClick={() => setMode(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Top bar shared by every page: wordmark (or custom left content), view, language and theme switches. */
export function AppBar({ left, right, showView = false }: { left?: ReactNode; right?: ReactNode; showView?: boolean }) {
  return (
    <div className="appbar">
      <div className="appbar-left">{left ?? <Wordmark />}</div>
      <div className="appbar-right">
        {right}
        {showView && <ViewToggle />}
        <LanguageToggle />
        <ThemeToggle />
      </div>
    </div>
  );
}
