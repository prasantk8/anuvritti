import { createRequire } from "node:module";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const audit = spawnSync("npm", ["audit", "--json"], { encoding: "utf8" });
if (!audit.stdout) {
  process.stderr.write(audit.stderr || "npm audit returned no report\n");
  process.exit(1);
}

const report = JSON.parse(audit.stdout);
const nodes = Object.keys(report.vulnerabilities ?? {}).sort();
if (nodes.length !== 0) {
  process.stderr.write(`npm advisory set changed: ${nodes.join(", ") || "none"}\n`);
  process.exit(1);
}

const xcodePackage = JSON.parse(readFileSync("node_modules/xcode/package.json", "utf8"));
const uuidPackage = JSON.parse(readFileSync("node_modules/uuid/package.json", "utf8"));
if (xcodePackage.version !== "3.0.1" || xcodePackage.dependencies?.uuid !== "11.1.1") {
  process.stderr.write("the reviewed xcode UUID patch is absent or must be retired\n");
  process.exit(1);
}
if (uuidPackage.version !== "11.1.1") {
  process.stderr.write(`xcode resolved an unreviewed UUID version: ${uuidPackage.version}\n`);
  process.exit(1);
}

const xcodeRoot = "node_modules/xcode/lib";
const sources = readdirSync(xcodeRoot)
  .filter((name) => name.endsWith(".js"))
  .map((name) => readFileSync(join(xcodeRoot, name), "utf8"))
  .join("\n");
if (!sources.includes("uuid.v4()") || /uuid\.v(?:1|3|5|6|7)\s*\(/.test(sources)) {
  process.stderr.write("xcode's UUID API use changed and needs a new compatibility review\n");
  process.exit(1);
}

const require = createRequire(import.meta.url);
const project = require("xcode").project("compatibility-smoke-test.pbxproj");
project.hash = { project: { objects: {} } };
const generated = project.generateUuid();
if (!/^[0-9A-F]{24}$/.test(generated)) {
  process.stderr.write("xcode could not generate its 24-character project identifier\n");
  process.exit(1);
}

console.log("zero npm advisories; reviewed xcode@3.0.1 UUID 11 compatibility patch is active");
