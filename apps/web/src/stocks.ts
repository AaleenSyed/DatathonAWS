import type { ExplainerPayload, TraceStep } from "@alphaforge/api-client";

// Stock cards and summary bolding. Every number comes from the run's trace (worker outputs), never from the
// answer text: analyze_asset gives a stock's own volatility, analyze_sector gives each member's. Names come
// from the same worker outputs (list_sectors, analyze_asset, member_metrics) and the explainer's member lists.

export interface StockInfo {
  ticker: string;
  name: string;
  /** Annualized volatility (fraction), or null when this run did not compute it. */
  vol: number | null;
  riskLabel: string | null;
  /** Trace step the volatility comes from. */
  step: number | null;
  currency: string | null;
}

type Obj = Record<string, unknown>;
const isObj = (x: unknown): x is Obj => typeof x === "object" && x !== null && !Array.isArray(x);
const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const str = (x: unknown) => (typeof x === "string" ? x : null);

interface Entry {
  name?: string;
  assetClass?: string;
  vol?: number;
  riskLabel?: string | null;
  step?: number;
  currency?: string | null;
}

/** Ticker -> what the trace says about it. Later steps (retries) win for the numbers. */
export function traceAssets(trace: TraceStep[], f?: ExplainerPayload | null): Map<string, Entry> {
  const out = new Map<string, Entry>();
  const put = (ticker: string, e: Entry) => out.set(ticker, { ...out.get(ticker), ...e });
  const steps = [...trace].sort((a, b) => a.step - b.step);
  for (const s of steps) {
    const o = s.output;
    if (!isObj(o) || o.status !== "ok" || !isObj(o.data)) continue;
    const d = o.data;
    const currency = str(o.currency);
    if (s.action === "list_sectors") {
      for (const group of Object.values(d)) {
        if (!isObj(group) || !Array.isArray(group.members)) continue;
        for (const m of group.members) {
          const t = isObj(m) ? str(m.ticker) : null;
          if (t) put(t, { name: str(m.name) ?? undefined, assetClass: str(m.asset_class) ?? undefined });
        }
      }
    } else if (s.action === "analyze_asset") {
      const t = str(d.ticker);
      if (t) {
        put(t, {
          name: str(d.name) ?? out.get(t)?.name,
          assetClass: str(d.asset_class) ?? out.get(t)?.assetClass,
          ...(isNum(d.annualized_vol) ? { vol: d.annualized_vol, step: s.step, currency, riskLabel: str(d.risk_label) } : {}),
        });
      }
    } else if (s.action === "analyze_sector" && isObj(d.member_metrics)) {
      for (const [t, m] of Object.entries(d.member_metrics)) {
        if (!isObj(m)) continue;
        put(t, {
          ...(str(m.name) ? { name: str(m.name)! } : {}),
          ...(str(m.asset_class) ? { assetClass: str(m.asset_class)! } : {}),
          ...(isNum(m.annualized_vol) ? { vol: m.annualized_vol, step: s.step, currency, riskLabel: str(m.risk_label) } : {}),
        });
      }
    }
  }
  // Names and classes the explainer collected from the same trace (fills gaps only).
  for (const target of [...(f?.requestedTargets ?? []), ...(f?.recommendedSectors ?? [])]) {
    for (const m of target.members) {
      const cur = out.get(m.ticker);
      if (!cur?.name || !cur.assetClass) put(m.ticker, { name: cur?.name ?? m.name, assetClass: cur?.assetClass ?? m.assetClass });
    }
  }
  return out;
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** Whole-word match that also works for tickers with dots or dashes (ATD.TO, BTC-USD). */
const wordRe = (s: string, flags = "g") => new RegExp(`(?<![\\w.&-])${escape(s)}(?![\\w-]|\\.\\w)`, flags);

/** Stocks (equities) the answer mentions by ticker or company name, in order of first mention. */
export function mentionedStocks(content: string, trace: TraceStep[], f?: ExplainerPayload | null): StockInfo[] {
  const assets = traceAssets(trace, f);
  const found: { at: number; info: StockInfo }[] = [];
  for (const [ticker, e] of assets) {
    if (e.assetClass !== "equity") continue;
    const at = [ticker, e.name]
      .filter((x): x is string => !!x && x.length > 1)
      .map((x) => content.search(wordRe(x, "")))
      .filter((i) => i >= 0);
    if (!at.length) continue;
    found.push({
      at: Math.min(...at),
      info: {
        ticker,
        name: e.name ?? ticker,
        vol: e.vol ?? null,
        riskLabel: e.riskLabel ?? null,
        step: e.step ?? null,
        currency: e.currency ?? null,
      },
    });
  }
  return found.sort((a, b) => a.at - b.at).map((x) => x.info);
}

/** Tickers, company names and sector names to bold in the summary (longest first). */
export function boldTerms(trace: TraceStep[], f?: ExplainerPayload | null): string[] {
  const terms = new Set<string>();
  for (const [ticker, e] of traceAssets(trace, f)) {
    terms.add(ticker);
    if (e.name) terms.add(e.name);
  }
  for (const s of [...(f?.requestedTargets ?? []), ...(f?.recommendedSectors ?? [])]) terms.add(s.name);
  return [...terms].filter((t) => t.length > 1).sort((a, b) => b.length - a.length);
}

// Markdown we must not touch: bold/italic spans, links (including claim chips), inline code.
const PROTECTED = /(\*\*[^*]+\*\*|__[^_]+__|\[[^\]]*\]\([^)]*\)|`[^`]*`)/g;

/** Wrap each mention of a term in **bold**, outside existing emphasis, links and code. */
export function boldMentions(markdown: string, terms: string[]): string {
  if (!terms.length) return markdown;
  const re = new RegExp(terms.map((t) => `(?<![\\w.&-])${escape(t)}(?![\\w-]|\\.\\w)`).join("|"), "g");
  return markdown
    .split(PROTECTED)
    .map((part, i) => (i % 2 ? part : part.replace(re, (m) => `**${m}**`)))
    .join("");
}

// ---------- Logos ----------

// Company websites for the universe's equities (assets_universe.csv). Used only to fetch a favicon-sized logo;
// any ticker missing here gets the lettered badge.
const DOMAINS: Record<string, string> = {
  "RY.TO": "rbc.com",
  "TD.TO": "td.com",
  "MFC.TO": "manulife.com",
  "ENB.TO": "enbridge.com",
  "CNQ.TO": "cnrl.com",
  "CNR.TO": "cn.ca",
  "FTS.TO": "fortisinc.com",
  "ATD.TO": "couche-tard.com",
  "SHOP.TO": "shopify.com",
  "CSU.TO": "csisoftware.com",
  AAPL: "apple.com",
  MSFT: "microsoft.com",
  NVDA: "nvidia.com",
  GOOGL: "abc.xyz",
  AMZN: "amazon.com",
  TSLA: "tesla.com",
  JPM: "jpmorganchase.com",
  JNJ: "jnj.com",
  PG: "pg.com",
  XOM: "exxonmobil.com",
};

/**
 * DuckDuckGo's public icon service: no API key, and it answers 404 (no image) for an unknown site, so the
 * <img> error handler can switch to the lettered badge.
 */
export function logoUrl(ticker: string): string | null {
  const domain = DOMAINS[ticker];
  return domain ? `https://icons.duckduckgo.com/ip3/${domain}.ico` : null;
}

/** "ATD.TO" -> "AT", "NVDA" -> "NV". */
export function badgeLetters(ticker: string): string {
  return ticker.replace(/[^A-Z]/gi, "").slice(0, 2).toUpperCase() || "?";
}

/** Volatility band for the ring colour: under 15% low, 15 to 30% medium, over 30% high. */
export function volBand(vol: number): "low" | "mid" | "high" {
  return vol < 0.15 ? "low" : vol <= 0.3 ? "mid" : "high";
}
