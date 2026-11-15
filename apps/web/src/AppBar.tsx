import { useState, type ReactNode } from "react";
import { useI18n } from "./i18n";

export function Wordmark() {
  return (
    <span className="wordmark">
      <span className="wordmark-mark" aria-hidden="true">
        A
      </span>
      AlphaForge <span className="wordmark-ai">AI</span>
    </span>
  );
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

/** Top bar shared by every page: wordmark (or custom left content), language and theme switches. */
export function AppBar({ left, right }: { left?: ReactNode; right?: ReactNode }) {
  return (
    <div className="appbar">
      <div className="appbar-left">{left ?? <Wordmark />}</div>
      <div className="appbar-right">
        {right}
        <LanguageToggle />
        <ThemeToggle />
      </div>
    </div>
  );
}
