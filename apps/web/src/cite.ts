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
