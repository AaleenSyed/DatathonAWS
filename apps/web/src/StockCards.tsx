import { useEffect, useState } from "react";
import { pct } from "./format";
import { useI18n } from "./i18n";
import { badgeLetters, logoUrl, volBand, type StockInfo } from "./stocks";

const LOGO_TIMEOUT_MS = 4000;
// Badge colours (white text on each meets 4.5:1).
const BADGE_BG = ["#3b4a7a", "#2f5f5c", "#5b3f73", "#6a4a2c", "#2e5a3a", "#6b3a45", "#3a556e"];

function badgeColor(ticker: string) {
  let h = 0;
  for (const c of ticker) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return BADGE_BG[h % BADGE_BG.length];
}

/** Company logo from a keyless icon service; the lettered badge when there is none, it fails, or it is slow. */
function Logo({ ticker }: { ticker: string }) {
  const url = logoUrl(ticker);
  const [state, setState] = useState<"loading" | "ok" | "failed">(url ? "loading" : "failed");
  useEffect(() => {
    if (state !== "loading") return;
    const timer = setTimeout(() => setState((s) => (s === "loading" ? "failed" : s)), LOGO_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [state]);
  return (
    <span className="stock-logo" style={{ background: state === "ok" ? undefined : badgeColor(ticker) }} aria-hidden="true">
      {state !== "ok" && <span className="stock-badge">{badgeLetters(ticker)}</span>}
      {url && state !== "failed" && (
        <img
          src={url}
          alt=""
          width={28}
          height={28}
          loading="lazy"
          referrerPolicy="no-referrer"
          style={{ visibility: state === "ok" ? "visible" : "hidden" }}
          onLoad={(e) => setState(e.currentTarget.naturalWidth > 2 ? "ok" : "failed")}
          onError={() => setState("failed")}
        />
      )}
    </span>
  );
}

const R = 25;
const C = 2 * Math.PI * R;
const RING_MAX = 0.6; // a full ring = 60% annualized volatility

/** Circular gauge: the arc length is the volatility (0 to 60%), the number sits in the middle. */
function VolRing({ vol }: { vol: number | null }) {
  const { locale } = useI18n();
  const band = vol == null ? "none" : volBand(vol);
  const share = vol == null ? 0 : Math.min(vol / RING_MAX, 1);
  return (
    <span className={`vol-ring band-${band}`}>
      <svg viewBox="0 0 64 64" width="68" height="68" aria-hidden="true">
        <circle className="ring-track" cx="32" cy="32" r={R} />
        {vol != null && (
          <circle
            className="ring-value"
            cx="32"
            cy="32"
            r={R}
            strokeDasharray={`${(share * C).toFixed(2)} ${C.toFixed(2)}`}
            transform="rotate(-90 32 32)"
          />
        )}
      </svg>
      <span className="ring-num">{vol == null ? "—" : pct(locale, vol)}</span>
    </span>
  );
}

function StockCard({ s, onCite }: { s: StockInfo; onCite: (steps: number[]) => void }) {
  const { t, locale } = useI18n();
  const band = s.vol == null ? null : volBand(s.vol);
  const bandText = band ? t(`stock.band.${band}`) : t("stock.noVol");
  const label = s.vol != null
    ? t("stock.aria", { name: s.name, ticker: s.ticker, vol: pct(locale, s.vol), band: bandText })
    : `${s.name} (${s.ticker}). ${bandText}`;
  const body = (
    <>
      <Logo ticker={s.ticker} />
      <span className="stock-id">
        <strong className="stock-name" title={s.name}>{s.name}</strong>
        <span className="stock-ticker">{s.ticker}</span>
        <span className={`stock-band${band ? ` band-${band}` : ""}`}>
          {s.vol != null ? t("stock.volLabel") : bandText}
          {s.vol != null && <small>{bandText}</small>}
        </span>
      </span>
      <VolRing vol={s.vol} />
    </>
  );
  if (s.step == null) {
    return (
      <li className="stock-card" aria-label={label}>
        {body}
      </li>
    );
  }
  return (
    <li>
      <button
        type="button"
        className="stock-card"
        aria-label={`${label} ${t("tr.open")} (${t("cite.step", { n: s.step })})`}
        title={`${t("tr.open")} · ${t("cite.step", { n: s.step })}`}
        onClick={() => onCite([s.step!])}
      >
        {body}
      </button>
    </li>
  );
}

/** One card per stock the answer mentions. */
export function StockCards({ stocks, onCite }: { stocks: StockInfo[]; onCite: (steps: number[]) => void }) {
  const { t } = useI18n();
  if (!stocks.length) return null;
  return (
    <section className="stocks" aria-label={t("stock.heading")}>
      <h4 className="section-label">{t("stock.heading")}</h4>
      <ul className="stock-list">
        {stocks.map((s) => (
          <StockCard key={s.ticker} s={s} onCite={onCite} />
        ))}
      </ul>
      <p className="note">{t("stock.note")}</p>
    </section>
  );
}
