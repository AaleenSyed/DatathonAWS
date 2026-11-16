import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { useI18n } from "./i18n";
import { useViewMode, type ViewMode } from "./view";

// Must match index.html. No saved choice = follow prefers-color-scheme; the switch saves "light" or "dark".
const THEME_KEY = "colorTheme";

/** Original mark: a four-point spark over a rising line (no real brand's logo). */
export function Wordmark() {
  return (
    <span className="wordmark">
      <svg className="wordmark-mark" viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
        <rect x=".75" y=".75" width="30.5" height="30.5" rx="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M16 7c.6 4.2 2.6 6.2 6.8 6.8-4.2.6-6.2 2.6-6.8 6.8-.6-4.2-2.6-6.2-6.8-6.8 4.2-.6 6.2-2.6 6.8-6.8z"
          fill="currentColor" />
        <path d="M9 25h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity=".55" />
      </svg>
      <span className="wordmark-text">
        AlphaForge <span className="wordmark-ai">AI</span>
      </span>
    </span>
  );
}

/** The agent's avatar in the chat: the logo's spark in a circle. */
export function AgentAvatar({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn("avatar size-9 text-base shadow-sm", className)}
    >
      <svg viewBox="0 0 32 32" width="16" height="16">
        <path d="M16 5c.8 5.4 3.6 8.2 9 9-5.4.8-8.2 3.6-9 9-.8-5.4-3.6-8.2-9-9 5.4-.8 8.2-3.6 9-9z" fill="currentColor" />
      </svg>
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
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme ?? "dark");
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
          localStorage.setItem(THEME_KEY, next);
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
      aria-label={`${t("lang.short")}: ${label}`}
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

/** Top bar shared by every page: skip link, then a header with the wordmark (or custom left content) and the view,
 *  language and theme switches. The `main` element of each page has id="main" (the skip link's target). */
export function AppBar({ left, right, showView = false }: { left?: ReactNode; right?: ReactNode; showView?: boolean }) {
  const { t } = useI18n();
  return (
    <>
      <a className="skip-link" href="#main">
        {t("a11y.skip")}
      </a>
      <header className="appbar">
        <nav className="appbar-nav" aria-label={t("a11y.nav")}>
          <div className="appbar-left">{left ?? <Wordmark />}</div>
          <div className="appbar-right">
            {right}
            {showView && <ViewToggle />}
            <LanguageToggle />
            <ThemeToggle />
          </div>
        </nav>
      </header>
    </>
  );
}
