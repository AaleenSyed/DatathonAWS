import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { LanguageProvider } from "./i18n";
import { ViewModeProvider } from "./view";
// Self-hosted fonts (SIL Open Font License), bundled by Vite: no request to a font CDN.
import "@fontsource-variable/inter";
import "@fontsource-variable/source-serif-4";
import "@fontsource-variable/source-serif-4/wght-italic.css";
// Tailwind (theme + utilities, no Preflight) wrapped around styles.css; see index.css.
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LanguageProvider>
      <ViewModeProvider>
        <App />
      </ViewModeProvider>
    </LanguageProvider>
  </StrictMode>,
);
