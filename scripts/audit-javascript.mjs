import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const acceptedNodes = [
  "@expo/cli",
  "@expo/config",
  "@expo/config-plugins",
  "@expo/inline-modules",
  "@expo/local-build-cache-provider",
  "@expo/metro-config",
  "@expo/prebuild-config",
  "expo",
  "expo-sharing",
  "uuid",
  "xcode",
];
const acceptedAdvisory = 1119441;

const audit = spawnSync("npm", ["audit", "--json"], { encoding: "utf8" });
if (!audit.stdout) {
  process.stderr.write(audit.stderr || "npm audit returned no report\n");
  process.exit(1);
}

const report = JSON.parse(audit.stdout);
const nodes = Object.keys(report.vulnerabilities ?? {}).sort();
if (JSON.stringify(nodes) !== JSON.stringify([...acceptedNodes].sort())) {
  process.stderr.write(`npm advisory set changed: ${nodes.join(", ") || "none"}\n`);
  process.exit(1);
}

const uuidVia = report.vulnerabilities.uuid?.via ?? [];
const advisories = uuidVia.filter((entry) => typeof entry === "object");
if (
  advisories.length !== 1 ||
  advisories[0].source !== acceptedAdvisory ||
  advisories[0].severity !== "moderate"
) {
  process.stderr.write("the accepted uuid advisory changed identity or severity\n");
  process.exit(1);
}

const xcodeRoot = "node_modules/xcode/lib";
const sources = readdirSync(xcodeRoot)
  .filter((name) => name.endsWith(".js"))
  .map((name) => readFileSync(join(xcodeRoot, name), "utf8"))
  .join("\n");
if (!sources.includes("uuid.v4()") || /uuid\.v(?:3|5|6)\s*\(/.test(sources)) {
  process.stderr.write("xcode's use of uuid is no longer outside the accepted advisory path\n");
  process.exit(1);
}

console.log(
  `accepted GHSA-w5hq-g745-h8pq for unreachable uuid v3/v5/v6 buffer APIs; ${nodes.length} derived moderate nodes, no others`,
);
