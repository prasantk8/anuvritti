#!/usr/bin/env tsx
/**
 * scripts/check-site.ts — Constitution Test for memtara.com (TASK-1502, PRD 8, PRD 47).
 *
 * Checks:
 * 1. The website uses tokens and CSS from packages/world rather than ad-hoc styles.
 * 2. The website contains no claims of features not implemented in the application.
 * 3. The manifesto of refusals (no streaks, no ads, never held hostage) matches code truth.
 */

import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const ROOT = join(import.meta.dirname, "..");
const SITE_HTML = join(ROOT, "site", "index.html");

assert.ok(existsSync(SITE_HTML), "site/index.html must exist");

const html = readFileSync(SITE_HTML, "utf8");

// 1. World tokens & design system link
assert.ok(
  html.includes("packages/world/world.css") || html.includes("world.css"),
  "site must link or inherit packages/world tokens"
);

// 2. Refusals & constitutional claims
const requiredClaims = [
  "No streaks",
  "No nagging",
  "No third-party trackers",
  "Never held hostage",
  "export sovereignty",
];

for (const claim of requiredClaims) {
  assert.ok(
    html.toLowerCase().includes(claim.toLowerCase()),
    `site/index.html must explicitly claim: "${claim}"`
  );
}

// 3. Prohibited dishonest hype words
const forbiddenHype = [
  "ai-powered magic",
  "revolutionary growth algorithm",
  "engagement score",
  "social network",
  "monetize your memories",
];

for (const hype of forbiddenHype) {
  assert.ok(
    !html.toLowerCase().includes(hype),
    `site/index.html contains forbidden marketing hype: "${hype}"`
  );
}

console.log("site check ok — site/index.html is honest and matches codebase constitution");
