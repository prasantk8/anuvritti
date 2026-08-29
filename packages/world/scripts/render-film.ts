/** Render complete offline film documents through packages/world/scenes. */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { join } from "node:path";
import { emitSceneCss } from "../scenes/css.ts";
import { renderScene, type SceneInput } from "../scenes/scene.ts";
import { assertFilmTextSupported, FILM_FONTS, FILM_SCRIPTS } from "../scenes/fonts.ts";
import { emitCss } from "../src/css.ts";

interface RenderBatch {
  readonly scenes: readonly SceneInput[];
}

// Resolved through Node rather than by path. One root lockfile owns every JavaScript
// package (TASK-723), so npm hoists @fontsource to the workspace root and
// `packages/world/node_modules/@fontsource` does not exist - the renderer that assumed it
// did could not draw a frame after the workspace was locked.
const require = createRequire(import.meta.url);

function font(family: string, weight: number, bytes: Buffer): string {
  return `@font-face {
  font-family: "${family}";
  font-style: normal;
  font-weight: ${weight};
  font-display: block;
  src: url(data:font/woff2;base64,${bytes.toString("base64")}) format("woff2");
}`;
}

const source = process.argv[2];
const destination = process.argv[3];
if (!source || !destination) throw new Error("usage: render-film.ts INPUT.json OUTPUT_DIR");

const batch = JSON.parse(readFileSync(source, "utf8")) as RenderBatch;
assertFilmTextSupported(
  batch.scenes.flatMap((scene) => [scene.heading, scene.body ?? "", scene.narration ?? ""])
);

const faces = FILM_FONTS.map((face) => {
  const bytes = readFileSync(require.resolve(`@fontsource/${face.file}`));
  return {
    ...face,
    bytes: bytes.byteLength,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    css: font(face.family, face.weight, bytes),
  };
});
const fontCss = faces.map((face) => face.css).join("\n");
mkdirSync(destination, { recursive: true });
writeFileSync(
  join(destination, "_fonts.json"),
  JSON.stringify(
    {
      scripts: FILM_SCRIPTS.map((script) => script.name),
      coverage: FILM_SCRIPTS.map((script) => ({ name: script.name, ranges: script.ranges })),
      faces: faces.map(({ css: _css, file: _file, ...face }) => face),
    },
    null,
    2
  )
);

// The app's generated stylesheet fetches its web fonts. A film replaces that import
// with the exact same families embedded above, so Chromium needs no base URL or network.
const worldCss = emitCss().replace(/^@import url\([^\n]+\);\n/m, "");
for (const scene of batch.scenes) {
  const document = renderScene(scene, {
    inlineCss: [fontCss, worldCss, emitSceneCss()],
  });
  writeFileSync(join(destination, `${scene.id}.html`), document);
}
