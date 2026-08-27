/** Refuse an unapproved requirements receipt before `make film-prepare` fetches anything. */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { approveRenderRequirements } from "../scenes/preparation.ts";

const requirementsPath = process.argv[2];
if (!requirementsPath) throw new Error("usage: prepare-film.ts RENDER_REQUIREMENTS.json");

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const worldPackage = JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as {
  name: string;
  version: string;
};
const requirements = JSON.parse(readFileSync(requirementsPath, "utf8")) as unknown;
const approved = approveRenderRequirements(requirements, worldPackage);
console.log(
  `approved ${worldPackage.name}@${worldPackage.version} for ${approved.scripts.join(", ") || "common punctuation only"}`
);
