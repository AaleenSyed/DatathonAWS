import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { LanguageProvider } from "./i18n";
import { ViewModeProvider } from "./view";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LanguageProvider>
      <ViewModeProvider>
        <App />
      </ViewModeProvider>
    </LanguageProvider>
  </StrictMode>,
);
