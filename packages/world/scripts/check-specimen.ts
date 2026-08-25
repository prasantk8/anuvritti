/**
 * The drift detector.
 *
 * The specimen exists so that a difference between the app and the film is *visible*
 * rather than discovered months later in a rendered video. That only holds if the
 * specimen is genuinely made of tokens. This check enforces three things:
 *
 *   1. every colour token is on the page, so nothing ships undocumented;
 *   2. the page names no colour of its own - drift starts with one hard-coded hex;
 *   3. every custom property it references actually exists in the emitted CSS.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { COLORS } from "../src/tokens.ts";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(root, "specimen", "index.html"), "utf8");
const css = readFileSync(join(root, "dist", "world.css"), "utf8");

const problems: string[] = [];

// 1. Coverage.
for (const c of COLORS) {
  if (!html.includes(`--w-color-${c.name}`)) {
    problems.push(`token --w-color-${c.name} is not shown anywhere on the specimen`);
  }
}

// 2. No colour of its own. `transparent` and `currentColor` are structural, not colour
//    decisions, and the waveform's inline pixel heights are sample data.
const style = html.slice(html.indexOf("<style>"), html.indexOf("</style>"));
for (const literal of style.match(/#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/g) ?? []) {
  problems.push(`the specimen names a colour of its own: ${literal}`);
}

// 3. No dangling references.
const declared = new Set(css.match(/--w-[a-z0-9-]+(?=\s*:)/g) ?? []);
// A reference whose suffix is interpolated - `var(--w-color-${c.name})` - is generated
// from the token list itself, so it is valid by construction and is skipped here.
for (const [, name, interpolated] of html.matchAll(/var\((--w-[a-z0-9-]+)(\$\{)?/g)) {
  if (interpolated) continue;
  if (!declared.has(name!)) problems.push(`specimen references ${name}, which world.css does not define`);
}

// 4. The CSP admits one font host and nothing else.
for (const src of html.match(/(?:src|href)="(https?:\/\/[^"]+)"/g) ?? []) {
  if (!src.includes("fonts.googleapis.com") && !src.includes("fonts.gstatic.com")) {
    problems.push(`external asset host: ${src}`);
  }
}

if (problems.length) {
  console.error(`specimen check failed (${problems.length}):`);
  for (const p of problems) console.error(`  - ${p}`);
  process.exit(1);
}
console.log(`specimen ok - ${COLORS.length} colour tokens shown, ${declared.size} properties declared, no drift`);
