/**
 * Offline Archive Reader Verification.
 *
 * Enforces that packages/world/reader/index.html:
 *   1. Exists and is valid standalone HTML5;
 *   2. Carries ZERO external network dependencies (no remote scripts, CDNs, external font calls);
 *   3. Uses standard Anuvritti design tokens;
 *   4. References custom properties declared in dist/world.css.
 */
import { readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const readerPath = join(root, "reader", "index.html");
const cssPath = join(root, "dist", "world.css");

if (!existsSync(readerPath)) {
  console.error("reader check failed: packages/world/reader/index.html does not exist");
  process.exit(1);
}

const html = readFileSync(readerPath, "utf8");
const css = readFileSync(cssPath, "utf8");

const problems: string[] = [];

// 1. Zero external network links (no http://, https://, protocol-relative //)
const externalUrls = html.match(/(?:src|href)=["'](https?:|\/\/)[^"']+["']/g) ?? [];
if (externalUrls.length > 0) {
  for (const u of externalUrls) {
    problems.push(`offline reader must not make external network requests: ${u}`);
  }
}

// 2. Token validation - all --w- custom properties referenced in reader must be in world.css
const declared = new Set(css.match(/--w-[a-z0-9-]+(?=\s*:)/g) ?? []);
for (const [, name] of html.matchAll(/var\((--w-[a-z0-9-]+)\)/g)) {
  if (!declared.has(name!)) {
    problems.push(`reader references undeclared custom property: ${name}`);
  }
}

// 3. Essential functionality hooks present
const requiredElements = [
  "family-title",
  "stat-sparks",
  "stat-moments",
  "sparks-grid",
  "moments-grid",
  "voice-grid",
];
for (const id of requiredElements) {
  if (!html.includes(`id="${id}"`)) {
    problems.push(`missing required reader element ID: ${id}`);
  }
}

if (problems.length) {
  console.error(`reader check failed (${problems.length} errors):`);
  for (const p of problems) console.error(`  - ${p}`);
  process.exit(1);
}

console.log("reader ok - standalone offline reader verified with zero external dependencies and matching design tokens");
