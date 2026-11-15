import type { ClaimKind } from "@alphaforge/api-client";

// Same patterns as server/explainer.py (TAG, STEP_NUMS, MAX_RANGE) and reviewer.py (STEP_REF), so a chip
// opens exactly the steps the explainer counts for that claim.
const TAG = /\[\s*(fact|assumption|scenario)\b[^\]]*\]/gi;
const STEP_REF = /\bfact:/i;
const STEP_NUMS = /(\d+)\s*[-–]\s*(\d+)|(\d+)/g;
const MAX_RANGE = 40;
const LINK_PREFIX = "#cite:";

/** Step numbers cited by one tag: "[fact: step 3, 7]" -> [3, 7], "[fact: step 17-24]" -> 17..24. */
export function citedSteps(tag: string): number[] {
  if (!STEP_REF.test(tag)) return [];
  const nums: number[] = [];
  for (const [, a, b, single] of tag.matchAll(STEP_NUMS)) {
    if (single) nums.push(Number(single));
    else if (Number(b) - Number(a) >= 0 && Number(b) - Number(a) <= MAX_RANGE) {
      for (let n = Number(a); n <= Number(b); n++) nums.push(n);
    } else nums.push(Number(a), Number(b));
  }
  return [...new Set(nums)];
}

/**
 * Replace each claim tag with a markdown link `[kind](#cite:kind:3,7)`, which the markdown renderer turns
 * into a chip. Steps that are not in the trace are dropped (same as the explainer).
 */
export function tagsToLinks(markdown: string, known: Set<number>): string {
  return markdown.replace(TAG, (tag, kind: string) => {
    const steps = citedSteps(tag).filter((n) => known.size === 0 || known.has(n));
    return ` [${kind.toLowerCase()}](${LINK_PREFIX}${kind.toLowerCase()}:${steps.join(",")})`;
  });
}

export function parseCiteHref(href: string | undefined): { kind: ClaimKind; steps: number[] } | null {
  if (!href?.startsWith(LINK_PREFIX)) return null;
  const [kind, steps = ""] = href.slice(LINK_PREFIX.length).split(":");
  if (kind !== "fact" && kind !== "assumption" && kind !== "scenario") return null;
  return { kind, steps: steps.split(",").filter(Boolean).map(Number) };
}

// ---------- Summary split ----------

// "## Summary" / "## Résumé" (the presenter's first heading); also accepts "**Summary**".
const SUMMARY_HEAD = /^\s{0,3}(?:#{1,6}\s*|\*\*\s*)(summary|résumé|resume)\s*(?:\*\*)?\s*:?\s*$/i;
const LIST_ITEM = /^\s*(?:[-*+]|\d+\.)\s+/;
const HEADING = /^\s{0,3}#{1,6}\s|^\s*\*\*[^*]+\*\*\s*:?\s*$|^\s*\*\*[^*]+:\*\*/;
const MAX_LINES_BEFORE = 6; // a short note (e.g. "Demo mode") may come before the summary
// "1. **Recommendation**", "- **Why it fits**:" — a list item that is a section title, not a summary bullet
const SECTION_ITEM = /^\s*(?:[-*+]|\d+\.)\s+\*\*[^*]+\*\*\s*:?\s*$|^\s*\d+\.\s+\*\*[^*]{3,40}\*\*\s*:/;

/**
 * Split an answer into the summary (everything up to the end of the summary's bullets) and the rest.
 * Null when there is no summary near the top (older answers): show the whole answer then.
 */
export function splitSummary(markdown: string): { summary: string; rest: string } | null {
  const lines = markdown.split("\n");
  const head = lines.findIndex((l) => SUMMARY_HEAD.test(l));
  if (head < 0 || head > MAX_LINES_BEFORE) return null;
  let end = head + 1;
  let items = 0;
  let ordered: boolean | null = null;
  while (end < lines.length) {
    const line = lines[end];
    if (line.trim() === "") {
      end++;
      continue;
    }
    if (LIST_ITEM.test(line) && !/^\s{2,}/.test(line)) {
      const isOrdered = /^\s*\d+\./.test(line);
      // Summary bullets are one kind of list. A list item that opens a section ("1. **Recommendation**") or
      // a change of list kind starts the details. An extra bullet (the presenter may write 4) stays visible.
      if (SECTION_ITEM.test(line) || (ordered !== null && isOrdered !== ordered)) break;
      ordered ??= isOrdered;
      items++;
    } else if (HEADING.test(line)) break;
    else if (items > 0 && !/^\s{2,}\S/.test(line)) break; // text after the bullets (not a continuation)
    end++;
  }
  const summary = lines.slice(0, end).join("\n").trimEnd();
  const rest = lines.slice(end).join("\n").trim();
  return { summary, rest };
}

// ---------- Short source labels ----------

const PROVIDERS: [RegExp, string][] = [
  [/^persona profile/i, "src.persona"],
  [/PolyFinances|Datathon 2026 brief/i, "src.brief"],
  [/Yahoo Finance/i, "Yahoo Finance"],
  [/Bank of Canada/i, "Bank of Canada"],
  [/\bFRED\b/, "FRED"],
  [/assets_universe/i, "src.universe"],
];
const PERIOD = /(\d{4})-\d{2}-\d{2}\s+to\s+(\d{4})-\d{2}-\d{2}/;
const CURRENCY = /(?:^|;\s*)([A-Z]{3})\s*$/;

/**
 * "Yahoo Finance via ... (https://...); FX: Bank of Canada ...; 2021-11-12 to 2026-11-12; CAD"
 * -> parts ["Yahoo Finance", "Bank of Canada"], years "2021–2026", currency "CAD".
 * Provider entries starting with "src." are i18n keys.
 */
export function sourceParts(source: string): { providers: string[]; years: string | null; currency: string | null } {
  const found = PROVIDERS.map(([re, label]) => ({ label, at: source.search(re) }))
    .filter((p) => p.at >= 0)
    .sort((a, b) => a.at - b.at)
    .map((p) => p.label);
  const period = source.match(PERIOD);
  const years = period ? (period[1] === period[2] ? period[1] : `${period[1]}–${period[2]}`) : null;
  return { providers: found.slice(0, 2), years, currency: source.match(CURRENCY)?.[1] ?? null };
}
