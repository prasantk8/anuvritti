/** Keep the compiler's static Unicode policy generated from packages/world, its sole owner. */

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { FILM_COMMON_RANGES, FILM_FONTS, FILM_SCRIPTS } from "../scenes/fonts.ts";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const repo = join(root, "..", "..");
const target = join(
  repo,
  "src",
  "anuvritti",
  "adapters",
  "film",
  "_world_font_policy.py"
);
const packageJson = JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as {
  name: string;
  version: string;
};

function ranges(value: readonly (readonly [number, number])[], indent = ""): string {
  const entries = value.map(([first, last]) => `${indent}    (${first}, ${last}),`).join("\n");
  return `(\n${entries}\n${indent})`;
}

const packages = Object.fromEntries(
  [...FILM_FONTS]
    .sort((left, right) => left.package.localeCompare(right.package))
    .map((face) => [face.package, face.version])
);
const scripts = FILM_SCRIPTS.map((script) => script.name);
const scriptRanges = FILM_SCRIPTS.map(
  (script) => `    ${JSON.stringify(script.name)}: ${ranges(script.ranges, "    ")},`
).join("\n");
const packageLines = Object.entries(packages)
  .map(([name, version]) => `    ${JSON.stringify(name)}: ${JSON.stringify(version)},`)
  .join("\n");

const scriptLines = scripts.map((name) => `    ${JSON.stringify(name)},`).join("\n");
const generated = `\"\"\"Generated from packages/world/scenes/fonts.ts. Do not edit by hand.\"\"\"\n\nfrom typing import Final\n\nWORLD_BUNDLE_NAME: Final = ${JSON.stringify(packageJson.name)}\nWORLD_BUNDLE_VERSION: Final = ${JSON.stringify(packageJson.version)}\nWORLD_FONT_PACKAGES: Final[dict[str, str]] = {\n${packageLines}\n}\nSCRIPT_ORDER: Final[tuple[str, ...]] = (\n${scriptLines}\n)\nCOMMON_RANGES: Final[tuple[tuple[int, int], ...]] = ${ranges(FILM_COMMON_RANGES)}\nSCRIPT_RANGES: Final[dict[str, tuple[tuple[int, int], ...]]] = {\n${scriptRanges}\n}\n`;

if (process.argv.includes("--check")) {
  const current = readFileSync(target, "utf8");
  if (current !== generated) {
    console.error("generated Python film font policy has drifted; run npm --prefix packages/world run policy:write");
    process.exit(1);
  }
  console.log(`film font policy ok - ${scripts.join(", ")} from ${Object.keys(packages).length} pinned packages`);
} else {
  writeFileSync(target, generated);
  console.log(target);
}
