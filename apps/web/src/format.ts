// Number and date formatting for the UI. Backend numbers are fractions (0.15 = 15%).

const formats = new Map<string, Intl.NumberFormat>();

function nf(locale: string, options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = `${locale}|${JSON.stringify(options)}`;
  let f = formats.get(key);
  if (!f) {
    f = new Intl.NumberFormat(locale, options);
    formats.set(key, f);
  }
  return f;
}

const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

/** 0.511 -> "51.1%" (en-CA) or "51,1 %" (fr-CA). One decimal, like the presenter's text. */
export function pct(locale: string, x: unknown): string {
  return isNum(x)
    ? nf(locale, { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(x)
    : "—";
}

export function num(locale: string, x: unknown, digits = 1): string {
  return isNum(x) ? nf(locale, { maximumFractionDigits: digits }).format(x) : "—";
}

/** "2026-11-12" -> "Nov 12, 2026" / "12 nov. 2026". Dates are calendar days, so format in UTC. */
export function fmtDate(locale: string, iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00Z` : iso);
  return Number.isNaN(d.getTime())
    ? iso
    : new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(d);
}

export function fmtTime(locale: string, iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : new Intl.DateTimeFormat(locale, { timeStyle: "medium" }).format(d);
}

/**
 * A persona limit or a suitability value: fraction, count (`min_asset_classes`), object (sector or
 * ticker -> fraction), list (ESG tickers) or null.
 */
export function fmtLimit(
  locale: string,
  rule: string,
  v: unknown,
  label: (name: string) => string,
  none: string,
): string {
  if (v == null) return "—";
  if (isNum(v)) return rule === "min_asset_classes" ? num(locale, v, 0) : pct(locale, v);
  if (Array.isArray(v)) return v.length ? v.map(String).join(", ") : none;
  if (typeof v === "object") {
    const parts = Object.entries(v as Record<string, unknown>).map(
      ([k, x]) => `${label(k)} ${isNum(x) ? pct(locale, x) : String(x)}`,
    );
    return parts.length ? parts.join(", ") : none;
  }
  return String(v);
}

/** [3, 7] -> "3, 7"; [17, 18, ..., 24] -> "17–24". */
export function stepList(steps: number[]): string {
  const sorted = [...new Set(steps)].sort((a, b) => a - b);
  const out: string[] = [];
  for (let i = 0; i < sorted.length; ) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j] + 1) j++;
    out.push(j - i >= 2 ? `${sorted[i]}–${sorted[j]}` : sorted.slice(i, j + 1).join(", "));
    i = j + 1;
  }
  return out.join(", ");
}
