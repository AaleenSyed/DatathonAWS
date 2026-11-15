import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Language } from "@alphaforge/api-client";

// Every UI string, in English and Canadian French (OQLF style: « », no space before ? and !,
// a non-breaking space before : and %, typographic apostrophe). Codes from the backend (rules, statuses,
// actors, sector names...) are translated here; free text written by the workers stays as sent.

const EN = {
  "app.disclaimer": "Educational simulation. Not personalized financial advice.",
  "app.demo": "Demo mode: scripted agent (no LLM), real worker numbers.",
  "lang.switchTo": "Afficher en français",
  "lang.short": "FR",
  "theme.toDark": "Switch to dark theme",
  "theme.toLight": "Switch to light theme",
  "view.label": "Level of detail",
  "view.simple": "Simple",
  "view.detailed": "Detailed",
  "view.simpleHint": "Summary first; details on demand",
  "view.detailedHint": "Open the full analysis and the evidence for every answer",

  "picker.step": "Step 1 of 2",
  "picker.title": "Who is investing today?",
  "picker.lead":
    "Pick the fictional investor profile closest to yours, then ask questions about markets and sectors in plain language.",
  "picker.cta": "Start",
  "picker.limits": "Assumed limits",
  "picker.limitsNote": "Profiles are fictional. Numeric limits are team assumptions.",
  "persona.nameAge": "{name}, {age}",
  "persona.amira": "Software engineer. High risk, 15+ year horizon, interested in AI, emerging tech and crypto, but still wants diversification.",
  "persona.mateo": "Operations manager, partner and 2 kids. Moderate risk, 8 to 12 year horizon, strong ESG preference.",
  "persona.robert": "Healthcare professional near retirement. Low to moderate risk, 3 to 5 year horizon, capital preservation.",

  "chat.back": "Change profile",
  "chat.profile": "Profile: {name}",
  "chat.emptyTitle": "Ask the agent a question",
  "chat.emptyHint": "It recommends a sector that fits {name}’s profile, with the numbers and where they come from.",
  "chat.you": "You",
  "chat.agent": "Agent",
  "chat.placeholder": "Ask a question…",
  "chat.inputLabel": "Your question",
  "chat.send": "Send",
  "chat.stop": "Stop",
  "chat.edit": "Edit",
  "chat.saveEdit": "Save and resend",
  "chat.cancelEdit": "Cancel edit",
  "chat.regenerate": "Regenerate",
  "chat.versions": "Other versions of this message",
  "chat.prev": "Previous version",
  "chat.next": "Next version",
  "chat.stopped": "Stopped",
  "chat.interrupted": "Interrupted",
  "chat.thinking": "Thinking",
  "chat.errCreate": "Could not create the conversation. Is the backend running?",
  "chat.errBranch": "Could not show this version.",
  "chat.errSend": "Not connected. Try again in a moment.",
  "chat.errServer": "Server error ({code})",
  "chat.errLoad": "Could not reload the conversation after reconnecting.",
  "chat.try": "Try",
  "chat.quoted": "“{q}”",
  "chat.ex.amira": "I only want AI and crypto, which industry should I focus on?",
  "chat.ex.mateo": "Which industry gives balanced growth for me?",
  "chat.ex.robert": "I want to put a big part of my savings in NVDA, good idea?",
  colon: ":",

  "status.idle": "Idle",
  "status.connecting": "Connecting…",
  "status.open": "Connected",
  "status.reconnecting": "Reconnecting…",
  "status.closed": "Disconnected",

  "stage.queued": "Waiting for another analysis to finish…",
  "stage.planning": "The boss agent is planning the analysis…",
  "stage.analyzing": "The workers are computing the numbers ({n} steps)…",
  "stage.reviewing": "The reviewer is checking the work…",
  "stage.writing": "The presenter is writing the answer…",
  "stage.checking": "The reviewer is checking every number in the answer…",
  "stage.done": "Done",
  "stage.note": "An analysis takes about a minute.",

  "sec.recommended": "Recommended sectors",
  "sec.requested": "Also considered",
  "sec.conflicts": "Conflicts noted by the boss agent",
  "sec.charts": "Risk charts",
  "sec.profile": "Profile check",
  "sec.market": "Market context",
  "sec.claims": "Claims in this answer ({n})",
  "sec.review": "Quality review",
  "sec.trace": "Trace ({n} steps)",
  "sec.limits": "Limitations and caveats",
  "sec.warnings": "Worker warnings ({n})",
  "ans.showFull": "Show full analysis",
  "ans.hideFull": "Hide full analysis",
  "ev.show": "Show the evidence",
  "ev.hide": "Hide the evidence",
  "ev.hint": "Profile check, risk charts, claims, quality review, limitations and the full trace.",
  "src.persona": "Persona profile",
  "src.brief": "Persona limits",
  "src.universe": "Asset universe",
  "src.other": "Trace",

  "m.vol": "Annualized volatility",
  "m.mdd": "Max drawdown",
  "m.ret": "Total return",
  "m.mom": "12-month momentum",
  "m.risk": "Risk",
  "m.members": "Members",
  "m.period": "{start} to {end}, {ccy}",
  "m.noBlend": "Building block: members are shown separately, with no blended figure.",
  "m.range": "{min} ({minT}) to {max} ({maxT})",
  "m.steps": "From trace steps",

  "chart.vol": "Annualized volatility, {start} to {end}",
  "chart.volLimit": "{name}’s volatility limit: {limit}",
  "chart.dd": "Worst fall in 2022 (stress test)",
  "chart.ddLimit": "{name}’s 2022 drawdown limit: {limit}",
  "chart.noLimit": "No limit of this kind for {name}.",
  "chart.noData": "No 2022 stress data in this run.",
  "chart.over": "above the limit",
  "chart.within": "within the limit",
  "chart.note": "Each bar is a number from the trace (hover for the step). Sector baskets are equal-weight.",

  "t.rule": "Rule",
  "t.limit": "Limit",
  "t.value": "Value",
  "t.status": "Status",
  "t.weight": "proposed weight {w}",
  "t.noWeight": "no weight proposed",
  "t.overall": "Overall",
  "t.explanationsEn": "",

  "mk.phase": "Business-cycle phase",
  "mk.rule": "Rule that fired",
  "mk.tilt": "Sectors that have historically tended to do well",
  "mk.vix": "VIX (fear gauge)",
  "mk.mood": "mood",
  "mk.credit": "High-yield credit spreads",
  "mk.rising": "rising: stress signal",
  "mk.notRising": "not rising",
  "mk.sentiment": "Consumer sentiment",
  "mk.note": "Historical tendencies, not predictions. As of {date}.",

  "rv.work": "Analysis check: every target analyzed, every limit evaluated, no data after the analysis date",
  "rv.answer": "Answer check: every number in the answer is found in the trace",
  "rv.pass": "Passed",
  "rv.fail": "Failed",
  "rv.retries": "{n} retry(ies)",
  "rv.incomplete": "The analysis is incomplete after the retries.",

  "lim.warnings": "Raw warnings from the worker results, as written by the code (in English).",
  "run.info": "Run {id}, analysis date {date}",
  "run.s3": "Trace saved to {uri}",
  "run.local": "Trace saved locally (no S3 bucket configured)",

  "tr.input": "Input",
  "tr.output": "Output",
  "tr.data": "Show data",
  "tr.truncated": "(truncated)",
  "tr.open": "Open in the trace",
  "cite.step": "step {n}",
  "cite.steps": "steps {n}",
} as const;

export type Key = keyof typeof EN;

const FR: Record<Key, string> = {
  "app.disclaimer": "Simulation éducative. Ne constitue pas un conseil financier personnalisé.",
  "app.demo": "Mode démo : agent scénarisé (sans LLM), vrais chiffres des workers.",
  "lang.switchTo": "Switch to English",
  "lang.short": "EN",
  "theme.toDark": "Passer au thème sombre",
  "theme.toLight": "Passer au thème clair",
  "view.label": "Niveau de détail",
  "view.simple": "Simple",
  "view.detailed": "Détaillé",
  "view.simpleHint": "Le résumé d’abord, les détails sur demande",
  "view.detailedHint": "Ouvrir l’analyse complète et les preuves de chaque réponse",

  "picker.step": "Étape 1 de 2",
  "picker.title": "Qui investit aujourd’hui?",
  "picker.lead":
    "Choisissez le profil d’investisseur fictif qui vous ressemble, puis posez vos questions sur les marchés et les secteurs en langage clair.",
  "picker.cta": "Commencer",
  "picker.limits": "Limites présumées",
  "picker.limitsNote": "Les profils sont fictifs. Les limites chiffrées sont des hypothèses de l’équipe.",
  "persona.nameAge": "{name}, {age} ans",
  "persona.amira": "Ingénieure logiciel. Risque élevé, horizon de plus de 15 ans, s’intéresse à l’IA, aux technologies émergentes et aux cryptomonnaies, mais veut rester diversifiée.",
  "persona.mateo": "Gestionnaire des opérations, en couple avec 2 enfants. Risque modéré, horizon de 8 à 12 ans, forte préférence ESG.",
  "persona.robert": "Professionnel de la santé proche de la retraite. Risque faible à modéré, horizon de 3 à 5 ans, préservation du capital.",

  "chat.back": "Changer de profil",
  "chat.profile": "Profil : {name}",
  "chat.emptyTitle": "Posez une question à l’Agent",
  "chat.emptyHint": "Il recommande un secteur adapté au profil de {name}, avec les chiffres et leur provenance.",
  "chat.you": "Vous",
  "chat.agent": "Agent",
  "chat.placeholder": "Posez une question…",
  "chat.inputLabel": "Votre question",
  "chat.send": "Envoyer",
  "chat.stop": "Arrêter",
  "chat.edit": "Modifier",
  "chat.saveEdit": "Enregistrer et renvoyer",
  "chat.cancelEdit": "Annuler la modification",
  "chat.regenerate": "Régénérer",
  "chat.versions": "Autres versions de ce message",
  "chat.prev": "Version précédente",
  "chat.next": "Version suivante",
  "chat.stopped": "Arrêté",
  "chat.interrupted": "Interrompu",
  "chat.thinking": "Réflexion en cours",
  "chat.errCreate": "Impossible de créer la conversation. Le serveur est-il démarré?",
  "chat.errBranch": "Impossible d’afficher cette version.",
  "chat.errSend": "Non connecté. Réessayez dans un instant.",
  "chat.errServer": "Erreur du serveur ({code})",
  "chat.errLoad": "Impossible de recharger la conversation après la reconnexion.",
  "chat.try": "Essayez",
  "chat.quoted": "«\u00a0{q}\u00a0»",
  "chat.ex.amira": "Je veux seulement de l’IA et des cryptos, sur quelle industrie me concentrer?",
  "chat.ex.mateo": "Quelle industrie m’offre une croissance équilibrée?",
  "chat.ex.robert": "Je veux placer une grande partie de mes économies dans NVDA, bonne idée?",
  colon: "\u00a0:",

  "status.idle": "Inactif",
  "status.connecting": "Connexion…",
  "status.open": "Connecté",
  "status.reconnecting": "Reconnexion…",
  "status.closed": "Déconnecté",

  "stage.queued": "En attente de la fin d’une autre analyse…",
  "stage.planning": "L’agent principal planifie l’analyse…",
  "stage.analyzing": "Les workers calculent les chiffres ({n} étapes)…",
  "stage.reviewing": "Le réviseur vérifie le travail…",
  "stage.writing": "Le présentateur rédige la réponse…",
  "stage.checking": "Le réviseur vérifie chaque chiffre de la réponse…",
  "stage.done": "Terminé",
  "stage.note": "Une analyse prend environ une minute.",

  "sec.recommended": "Secteurs recommandés",
  "sec.requested": "Aussi examinés",
  "sec.conflicts": "Conflits relevés par l’agent principal",
  "sec.charts": "Graphiques de risque",
  "sec.profile": "Vérification du profil",
  "sec.market": "Contexte de marché",
  "sec.claims": "Affirmations de cette réponse ({n})",
  "sec.review": "Contrôle de qualité",
  "sec.trace": "Trace ({n} étapes)",
  "sec.limits": "Limites et mises en garde",
  "sec.warnings": "Avertissements des workers ({n})",
  "ans.showFull": "Afficher l’analyse complète",
  "ans.hideFull": "Masquer l’analyse complète",
  "ev.show": "Afficher les preuves",
  "ev.hide": "Masquer les preuves",
  "ev.hint": "Vérification du profil, graphiques de risque, affirmations, contrôle de qualité, limites et trace complète.",
  "src.persona": "Profil du persona",
  "src.brief": "Limites du profil",
  "src.universe": "Univers d’actifs",
  "src.other": "Trace",

  "m.vol": "Volatilité annualisée",
  "m.mdd": "Baisse maximale",
  "m.ret": "Rendement total",
  "m.mom": "Momentum sur 12 mois",
  "m.risk": "Risque",
  "m.members": "Membres",
  "m.period": "du {start} au {end}, {ccy}",
  "m.noBlend": "Bloc de base : les membres sont présentés séparément, sans chiffre combiné.",
  "m.range": "de {min} ({minT}) à {max} ({maxT})",
  "m.steps": "Tiré des étapes de la trace",

  "chart.vol": "Volatilité annualisée, du {start} au {end}",
  "chart.volLimit": "Limite de volatilité de {name} : {limit}",
  "chart.dd": "Pire baisse en 2022 (test de stress)",
  "chart.ddLimit": "Limite de baisse 2022 de {name} : {limit}",
  "chart.noLimit": "Aucune limite de ce type pour {name}.",
  "chart.noData": "Pas de données de stress 2022 dans cette analyse.",
  "chart.over": "au-dessus de la limite",
  "chart.within": "dans la limite",
  "chart.note": "Chaque barre est un chiffre de la trace (survolez pour voir l’étape). Les paniers sectoriels sont équipondérés.",

  "t.rule": "Règle",
  "t.limit": "Limite",
  "t.value": "Valeur",
  "t.status": "Statut",
  "t.weight": "poids proposé {w}",
  "t.noWeight": "aucun poids proposé",
  "t.overall": "Global",
  "t.explanationsEn": "Les explications détaillées viennent du worker de convenance, en anglais.",

  "mk.phase": "Phase du cycle économique",
  "mk.rule": "Règle déclenchée",
  "mk.tilt": "Secteurs qui ont historiquement eu tendance à bien faire",
  "mk.vix": "VIX (indice de la peur)",
  "mk.mood": "humeur",
  "mk.credit": "Écarts de crédit à haut rendement",
  "mk.rising": "en hausse : signal de stress",
  "mk.notRising": "pas en hausse",
  "mk.sentiment": "Sentiment des consommateurs",
  "mk.note": "Tendances historiques, pas des prévisions. Au {date}.",

  "rv.work": "Vérification de l’analyse : chaque cible analysée, chaque limite évaluée, aucune donnée après la date d’analyse",
  "rv.answer": "Vérification de la réponse : chaque chiffre de la réponse se retrouve dans la trace",
  "rv.pass": "Réussi",
  "rv.fail": "Échoué",
  "rv.retries": "{n} reprise(s)",
  "rv.incomplete": "L’analyse est incomplète après les reprises.",

  "lim.warnings": "Avertissements bruts des résultats des workers, tels qu’écrits par le code (en anglais).",
  "run.info": "Analyse {id}, date d’analyse {date}",
  "run.s3": "Trace enregistrée dans {uri}",
  "run.local": "Trace enregistrée localement (aucun compartiment S3 configuré)",

  "tr.input": "Entrée",
  "tr.output": "Sortie",
  "tr.data": "Voir les données",
  "tr.truncated": "(tronqué)",
  "tr.open": "Ouvrir dans la trace",
  "cite.step": "étape {n}",
  "cite.steps": "étapes {n}",
};

// Backend codes -> display labels. Unknown codes are shown as sent.
type CodeMap = Record<string, { en: string; fr: string }>;

const CODES: Record<string, CodeMap> = {
  status: {
    conflict: { en: "Conflict", fr: "Conflit" },
    flag: { en: "Flag", fr: "Signalement" },
    info: { en: "Info", fr: "Information" },
    pass: { en: "Pass", fr: "Conforme" },
    not_applicable: { en: "N/A", fr: "S. O." },
    not_evaluated: { en: "Not evaluated", fr: "Non évalué" },
    incomplete: { en: "Incomplete", fr: "Incomplet" },
  },
  rule: {
    crypto_max: { en: "Crypto cap", fr: "Plafond crypto" },
    single_stock_max: { en: "Single-stock cap", fr: "Plafond par titre" },
    sector_max: { en: "Sector cap", fr: "Plafond sectoriel" },
    min_asset_classes: { en: "Minimum asset classes", fr: "Catégories d’actifs minimales" },
    vol_max: { en: "Volatility limit", fr: "Limite de volatilité" },
    bonds_min: { en: "Bonds minimum", fr: "Minimum en obligations" },
    bonds_cash_min: { en: "Bonds/cash minimum", fr: "Minimum obligations et encaisse" },
    stress_2022_max_drawdown: { en: "2022 drawdown limit", fr: "Limite de baisse en 2022" },
    esg_review: { en: "ESG review", fr: "Examen ESG" },
  },
  kind: {
    asset: { en: "Single asset", fr: "Actif unique" },
    industry: { en: "Industry, equal-weight basket", fr: "Industrie, panier équipondéré" },
    building_block: { en: "Building block", fr: "Bloc de base" },
  },
  risk: {
    Low: { en: "Low", fr: "Faible" },
    Moderate: { en: "Moderate", fr: "Modéré" },
    High: { en: "High", fr: "Élevé" },
    "Very High": { en: "Very high", fr: "Très élevé" },
  },
  trend: {
    "above 200-day average": { en: "above its 200-day average", fr: "au-dessus de sa moyenne sur 200 jours" },
    "below 200-day average": { en: "below its 200-day average", fr: "sous sa moyenne sur 200 jours" },
  },
  phase: {
    "Recession risk": { en: "Recession risk", fr: "Risque de récession" },
    "Early cycle": { en: "Early cycle", fr: "Début de cycle" },
    "Mid cycle": { en: "Mid cycle", fr: "Milieu de cycle" },
    "Late cycle": { en: "Late cycle", fr: "Fin de cycle" },
  },
  mood: {
    "calm/hope": { en: "calm / hope", fr: "calme / espoir" },
    normal: { en: "normal", fr: "normale" },
    fear: { en: "fear", fr: "peur" },
  },
  sector: {
    "Information Technology": { en: "Information Technology", fr: "Technologies de l’information" },
    "Consumer Staples": { en: "Consumer Staples", fr: "Biens de consommation de base" },
    "Consumer Discretionary": { en: "Consumer Discretionary", fr: "Consommation discrétionnaire" },
    Utilities: { en: "Utilities", fr: "Services publics" },
    Energy: { en: "Energy", fr: "Énergie" },
    Financials: { en: "Financials", fr: "Services financiers" },
    "Health Care": { en: "Health Care", fr: "Soins de santé" },
    Industrials: { en: "Industrials", fr: "Industrie" },
    "Communication Services": { en: "Communication Services", fr: "Services de communication" },
    Materials: { en: "Materials", fr: "Matériaux" },
    "Real Estate": { en: "Real Estate", fr: "Immobilier" },
    Bonds: { en: "Bonds", fr: "Obligations" },
    "Broad market": { en: "Broad market", fr: "Marché global" },
    Gold: { en: "Gold", fr: "Or" },
    "Crypto asset": { en: "Crypto assets", fr: "Cryptoactifs" },
  },
  actor: {
    user: { en: "User", fr: "Utilisateur" },
    boss: { en: "Boss agent (LLM)", fr: "Agent principal (LLM)" },
    "worker:data_retriever": { en: "Data retriever", fr: "Collecte des données" },
    "worker:risk_analyst": { en: "Risk analyst", fr: "Analyse du risque" },
    "worker:suitability": { en: "Suitability check", fr: "Vérification de la convenance" },
    "worker:market_context": { en: "Market context", fr: "Contexte de marché" },
    reviewer: { en: "Reviewer", fr: "Réviseur" },
    presenter: { en: "Presenter (LLM)", fr: "Présentateur (LLM)" },
    pipeline: { en: "Pipeline", fr: "Pipeline" },
  },
  claim: {
    fact: { en: "Fact", fr: "Fait" },
    assumption: { en: "Assumption", fr: "Hypothèse" },
    scenario: { en: "Scenario", fr: "Scénario" },
  },
  caveat: {
    simulation_only: {
      en: "Educational simulation for a fictional persona. No real transactions.",
      fr: "Simulation éducative pour un profil fictif. Aucune transaction réelle.",
    },
    past_performance: {
      en: "Past returns do not predict future returns.",
      fr: "Les rendements passés ne garantissent pas les rendements futurs.",
    },
    survivorship_bias: {
      en: "Survivorship bias: the asset universe was picked in 2026.",
      fr: "Biais du survivant : l’univers d’actifs a été choisi en 2026.",
    },
    fred_revised_vintages: {
      en: "FRED macro values are revised vintages, not the numbers known at the time.",
      fr: "Les données macro de FRED sont des valeurs révisées, pas celles connues à l’époque.",
    },
    macro_publication_lag: {
      en: "Monthly macro data is used only from its assumed publication date.",
      fr: "Les données macro mensuelles ne sont utilisées qu’à partir de leur date de publication présumée.",
    },
    equal_weight_baskets: {
      en: "A sector is an equal-weight basket of the universe’s assets, rebalanced daily.",
      fr: "Un secteur est un panier équipondéré des actifs de l’univers, rééquilibré chaque jour.",
    },
  },
};

export type CodeKind = keyof typeof CODES;

interface I18n {
  lang: Language;
  locale: string;
  setLang: (lang: Language) => void;
  t: (key: Key, vars?: Record<string, string | number>) => string;
  code: (kind: CodeKind, value: string | null | undefined) => string;
}

const Ctx = createContext<I18n | null>(null);

function initialLang(): Language {
  try {
    const saved = localStorage.getItem("lang");
    if (saved === "en" || saved === "fr") return saved;
  } catch {
    /* storage unavailable */
  }
  return navigator.language?.toLowerCase().startsWith("fr") ? "fr" : "en";
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Language>(initialLang);
  useEffect(() => {
    document.documentElement.lang = lang === "fr" ? "fr-CA" : "en-CA";
  }, [lang]);
  const setLang = useCallback((next: Language) => {
    setLangState(next);
    try {
      localStorage.setItem("lang", next);
    } catch {
      /* storage unavailable: the choice still applies for this visit */
    }
  }, []);
  const value = useMemo<I18n>(() => {
    const dict = lang === "fr" ? FR : EN;
    return {
      lang,
      locale: lang === "fr" ? "fr-CA" : "en-CA",
      setLang,
      t: (key, vars) =>
        Object.entries(vars ?? {}).reduce((s, [k, v]) => s.split(`{${k}}`).join(String(v)), dict[key] as string),
      code: (kind, value) => (value == null ? "—" : CODES[kind]?.[value]?.[lang] ?? value),
    };
  }, [lang, setLang]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useI18n outside LanguageProvider");
  return ctx;
}
