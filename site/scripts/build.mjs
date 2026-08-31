import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { execSync } from "node:child_process";

const ROOT = join(import.meta.dirname, "../..");
const SITE_DIR = join(ROOT, "site");
const DIST_DIR = join(SITE_DIR, "dist");
const WORLD_DIR = join(ROOT, "packages", "world");

console.log("Building packages/world...");
execSync("npm --prefix " + WORLD_DIR + " run build --silent", { stdio: "inherit" });

mkdirSync(DIST_DIR, { recursive: true });

// Copy world.css
const worldCssSrc = join(WORLD_DIR, "dist", "world.css");
const worldCssDest = join(DIST_DIR, "world.css");
cpSync(worldCssSrc, worldCssDest);

// Read site index.html, rewrite CSS path for root serving, and write to dist
let html = readFileSync(join(SITE_DIR, "index.html"), "utf8");
html = html.replace('../packages/world/dist/world.css', './world.css');
writeFileSync(join(DIST_DIR, "index.html"), html, "utf8");

// Copy headers, redirects, and CNAME if present
const headersSrc = join(SITE_DIR, "_headers");
if (existsSync(headersSrc)) {
  cpSync(headersSrc, join(DIST_DIR, "_headers"));
}
const cnameSrc = join(SITE_DIR, "CNAME");
if (existsSync(cnameSrc)) {
  cpSync(cnameSrc, join(DIST_DIR, "CNAME"));
}

console.log("Built site/dist successfully for Pages deployment.");
