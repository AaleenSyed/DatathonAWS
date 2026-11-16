// WCAG 2.2 contrast check of the design tokens in src/styles.css, both themes.
// Run: node apps/web/scripts/contrast.mjs   (exit code 1 if a pair is below its minimum)
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const css = readFileSync(fileURLToPath(new URL("../src/styles.css", import.meta.url)), "utf8");

function block(selector) {
  const i = css.indexOf(selector + " {");
  if (i < 0) throw new Error("block not found: " + selector);
  const body = css.slice(css.indexOf("{", i) + 1, css.indexOf("\n}", i));
  const vars = {};
  for (const m of body.matchAll(/(--[\w-]+):\s*([^;]+);/g)) vars[m[1]] = m[2].trim();
  return vars;
}

const brand = block(":root");
const themes = {
  light: { ...brand, ...block(':root, :root[data-theme="light"]') },
  dark: { ...brand, ...block(':root[data-theme="dark"]') },
};
// Inside the celadon bubble the variables are re-pointed (light theme only).
const bubble = block(':root:not([data-theme="dark"]) .persona-bubble');

function parse(v) {
  v = v.trim();
  if (v.startsWith("#")) {
    const h = v.length === 4 ? [...v.slice(1)].map((c) => c + c).join("") : v.slice(1);
    return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16), a: 1 };
  }
  const m = v.match(/rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*(?:\/\s*([\d.]+)%)?\s*\)/);
  if (!m) throw new Error("cannot parse colour: " + v);
  return { r: +m[1], g: +m[2], b: +m[3], a: m[4] === undefined ? 1 : +m[4] / 100 };
}
const over = (fg, bg) => ({
  r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1,
});
const lum = ({ r, g, b }) => {
  const f = (c) => ((c /= 255) <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
};
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

let failed = 0;
function check(theme, label, fgVal, bgVal, min, baseVal) {
  const base = parse(baseVal ?? bgVal);
  const bg = over(parse(bgVal), base);
  const fg = over(parse(fgVal), bg);
  const r = ratio(fg, bg);
  const ok = r >= min;
  if (!ok) failed++;
  console.log(`${ok ? "pass" : "FAIL"}  ${theme.padEnd(5)} ${r.toFixed(2).padStart(5)}:1 (min ${min})  ${label}`);
}

for (const [name, t] of Object.entries(themes)) {
  const v = (k) => t[k];
  // Text
  check(name, "ink on page", v("--ink"), v("--bg"), 4.5);
  check(name, "body text on page", v("--text"), v("--bg"), 4.5);
  check(name, "muted text on page", v("--muted"), v("--bg"), 4.5);
  check(name, "muted text on card", v("--muted"), v("--surface"), 4.5);
  check(name, "muted text on surface-2", v("--muted"), v("--surface-2"), 4.5);
  check(name, "link on page", v("--link"), v("--bg"), 4.5);
  check(name, "primary button text", v("--on-primary"), v("--primary"), 4.5);
  check(name, "user bubble text", v("--on-bubble-user"), v("--bubble-user"), 4.5);
  check(name, "assistant bubble text", v("--bubble-ai-ink"), v("--bubble-ai"), 4.5);
  check(name, "pass text on its tint", v("--pass-ink"), v("--pass-soft"), 4.5, v("--surface"));
  check(name, "caution text on its tint", v("--caution-ink"), v("--caution-soft"), 4.5, v("--surface"));
  check(name, "conflict text on its tint", v("--conflict-ink"), v("--conflict-soft"), 4.5, v("--surface"));
  // Non-text: controls, focus, chart bars (3:1)
  check(name, "input / outline-button border on page", v("--control-border"), v("--bg"), 3);
  check(name, "input / outline-button border on card", v("--control-border"), v("--surface"), 3);
  check(name, "focus ring on page", v("--focus"), v("--bg"), 3);
  check(name, "focus ring on card", v("--focus"), v("--surface"), 3);
  check(name, "chart bar on its track", v("--bar"), v("--surface-2"), 3);
  check(name, "primary button on page (selected card, switch)", v("--primary"), v("--bg"), 3);
}
// Inside the celadon bubble (light theme): re-pointed text colours and nested cards.
const L = themes.light;
check("light", "bubble: body text on celadon", bubble["--text"], L["--bubble-ai"], 4.5);
check("light", "bubble: muted text on celadon", bubble["--muted"], L["--bubble-ai"], 4.5);
check("light", "bubble: muted text on nested card", bubble["--muted"], bubble["--surface"], 4.5);
check("light", "bubble: grape accent on celadon", L["--dusty-grape"], L["--bubble-ai"], 4.5);
check("light", "bubble: control border on celadon", bubble["--control-border"], L["--bubble-ai"], 3);
check("light", "bubble: focus ring on celadon", L["--focus"], L["--bubble-ai"], 3);
// Brand rules from the brief (informational thresholds)
check("light", "dusty grape text on white", L["--dusty-grape"], "#FFFFFF", 4.5);
check("light", "lavender purple text on white (accents only)", L["--lavender-purple"], "#FFFFFF", 4.5);
check("light", "dusty olive on white: large text / icons only", L["--dusty-olive"], "#FFFFFF", 3);
check("light", "grape text on celadon", L["--dusty-grape"], L["--celadon"], 4.5);
check("light", "near-black text on willow green", "#1B1630", L["--willow-green"], 4.5);

console.log(failed ? `\n${failed} pair(s) below the minimum` : "\nAll pairs meet their minimum");
process.exit(failed ? 1 : 0);
