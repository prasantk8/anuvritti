/** Render complete offline film documents through packages/world/scenes. */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { emitSceneCss } from "../scenes/css.ts";
import { renderScene, type SceneInput } from "../scenes/scene.ts";
import { emitCss } from "../src/css.ts";

interface RenderBatch {
  readonly scenes: readonly SceneInput[];
}

const require = createRequire(import.meta.url);

function font(family: string, weight: number, file: string): string {
  const bytes = readFileSync(require.resolve(`@fontsource/${file}`));
  return `@font-face {
  font-family: "${family}";
  font-style: normal;
  font-weight: ${weight};
  font-display: block;
  src: url(data:font/woff2;base64,${bytes.toString("base64")}) format("woff2");
}`;
}

const fontCss = [
  font("Newsreader", 400, "newsreader/files/newsreader-latin-400-normal.woff2"),
  font("IBM Plex Sans", 400, "ibm-plex-sans/files/ibm-plex-sans-latin-400-normal.woff2"),
  font("IBM Plex Sans", 500, "ibm-plex-sans/files/ibm-plex-sans-latin-500-normal.woff2"),
].join("\n");

const source = process.argv[2];
const destination = process.argv[3];
if (!source || !destination) throw new Error("usage: render-film.ts INPUT.json OUTPUT_DIR");

const batch = JSON.parse(readFileSync(source, "utf8")) as RenderBatch;
mkdirSync(destination, { recursive: true });

// The app's generated stylesheet fetches its web fonts. A film replaces that import
// with the exact same families embedded above, so Chromium needs no base URL or network.
const worldCss = emitCss().replace(/^@import url\([^\n]+\);\n/m, "");
for (const scene of batch.scenes) {
  const document = renderScene(scene, {
    inlineCss: [fontCss, worldCss, emitSceneCss()],
  });
  writeFileSync(join(destination, `${scene.id}.html`), document);
}
