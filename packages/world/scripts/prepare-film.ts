/** Refuse an unapproved requirements receipt before `make film-prepare` fetches anything. */

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { FILM_FONTS } from "../scenes/fonts.ts";
import {
  approveRenderRequirements,
  assertInstalledFilmFontDigests,
} from "../scenes/preparation.ts";

const requirementsPath = process.argv[2];
if (!requirementsPath) throw new Error("usage: prepare-film.ts RENDER_REQUIREMENTS.json");

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const worldPackage = JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as {
  name: string;
  version: string;
};
const requirements = JSON.parse(readFileSync(requirementsPath, "utf8")) as unknown;
const approved = approveRenderRequirements(requirements, worldPackage);
if (process.argv.includes("--requirements-only")) {
  console.log(
    `approved ${worldPackage.name}@${worldPackage.version} for ${approved.scripts.join(", ") || "common punctuation only"}`
  );
  process.exit(0);
}

const require = createRequire(import.meta.url);
const digests = Object.fromEntries(
  FILM_FONTS.map((face) => {
    const bytes = readFileSync(require.resolve(`@fontsource/${face.file}`));
    return [face.file, createHash("sha256").update(bytes).digest("hex")];
  })
);
assertInstalledFilmFontDigests(digests);
console.log(
  `ready ${worldPackage.name}@${worldPackage.version} for ${approved.scripts.join(", ") || "common punctuation only"}; ${FILM_FONTS.length} font files verified`
);
