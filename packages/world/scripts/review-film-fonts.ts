/** Render approved and candidate font bytes as the same multilingual film frames. */

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { emitSceneCss } from "../scenes/css.ts";
import { FILM_FONTS, type FilmFontFace, type FilmScript } from "../scenes/fonts.ts";
import { renderScene, FRAME, type SceneInput } from "../scenes/scene.ts";
import { assertInstalledFilmFontDigests } from "../scenes/preparation.ts";
import { emitCss } from "../src/css.ts";
import { comparePngs, type DifferenceMetrics } from "./png-difference.ts";

interface FaceBytes extends FilmFontFace {
  readonly bytes: Buffer;
  readonly digest: string;
}

interface ReviewFace {
  readonly family: string;
  readonly role: string;
  readonly weight: number;
  readonly script: string;
  readonly file: string;
  readonly approved_sha256: string;
  readonly candidate_sha256: string;
  readonly changed: boolean;
}

interface ReviewComparison extends DifferenceMetrics {
  readonly script: FilmScript;
  readonly approved: string;
  readonly candidate: string;
  readonly difference: string;
}

const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(packageRoot, "..", "..");
const require = createRequire(import.meta.url);

const SAMPLES: Readonly<Record<FilmScript, SceneInput>> = {
  Latin: {
    id: "font-review-latin",
    kind: "MOMENT",
    heading: "The year Aarav turned seven",
    body: "“I can do this myself now.” — 2026",
  },
  Arabic: {
    id: "font-review-arabic",
    kind: "MOMENT",
    heading: "أول مرة نزل فيها وحده",
    body: "قالها بابا — ٢٠٢٦",
  },
  Devanagari: {
    id: "font-review-devanagari",
    kind: "MOMENT",
    heading: "पहली बार वह अकेले फिसला",
    body: "पापा ने लिखा — २०२६",
  },
};

function digest(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function fontCss(face: FaceBytes): string {
  return `@font-face {
  font-family: "${face.family}";
  font-style: normal;
  font-weight: ${face.weight};
  font-display: block;
  src: url(data:font/woff2;base64,${face.bytes.toString("base64")}) format("woff2");
}`;
}

function approvedFaces(): FaceBytes[] {
  const faces = FILM_FONTS.map((face) => {
    const bytes = readFileSync(require.resolve(`@fontsource/${face.file}`));
    return { ...face, bytes, digest: digest(bytes) };
  });
  assertInstalledFilmFontDigests(Object.fromEntries(faces.map((face) => [face.file, face.digest])));
  return faces;
}

function candidateFaces(candidateRoot: string, candidateVersion: string): FaceBytes[] {
  const packages = new Set(FILM_FONTS.map((face) => face.package));
  for (const packageName of packages) {
    const manifest = JSON.parse(
      readFileSync(join(candidateRoot, packageName, "package.json"), "utf8")
    ) as { version?: string };
    if (manifest.version !== candidateVersion) {
      throw new Error(
        `${packageName} is ${manifest.version ?? "unversioned"}; expected candidate ${candidateVersion}`
      );
    }
  }
  return FILM_FONTS.map((face) => {
    const bytes = readFileSync(join(candidateRoot, "@fontsource", face.file));
    return { ...face, bytes, digest: digest(bytes) };
  });
}

function renderDocuments(label: string, faces: FaceBytes[], output: string): string[] {
  const embeddedFonts = faces.map(fontCss).join("\n");
  const worldCss = emitCss().replace(/^@import url\([^\n]+\);\n/m, "");
  return Object.entries(SAMPLES).map(([script, scene]) => {
    const basename = `${label}-${script.toLowerCase()}`;
    const html = join(output, `${basename}.html`);
    writeFileSync(
      html,
      renderScene(scene, { inlineCss: [embeddedFonts, worldCss, emitSceneCss()] })
    );
    return basename;
  });
}

function screenshot(basenames: string[], output: string, playwright: string): void {
  for (const basename of basenames) {
    const html = join(output, `${basename}.html`);
    const png = join(output, `${basename}.png`);
    const rendered = spawnSync(
      playwright,
      [
        "screenshot",
        "--browser",
        "chromium",
        "--viewport-size",
        `${FRAME.width},${FRAME.height}`,
        "--wait-for-timeout",
        "100",
        pathToFileURL(html).href,
        png,
      ],
      { encoding: "utf8" }
    );
    if (rendered.status !== 0 || !existsSync(png)) {
      throw new Error(
        `Chromium did not render ${basename}: ${rendered.stderr || rendered.stdout || "no PNG"}`
      );
    }
  }
}

function argument(name: string): string {
  const position = process.argv.indexOf(name);
  const value = position < 0 ? undefined : process.argv[position + 1];
  if (!value) throw new Error(`missing ${name}`);
  return value;
}

function percent(fraction: number): string {
  return `${(fraction * 100).toFixed(4)}%`;
}

function reviewMarkdown(
  candidateVersion: string,
  faces: ReviewFace[],
  comparisons: ReviewComparison[]
): string {
  const rows = (["Latin", "Arabic", "Devanagari"] as const)
    .map(
      (script) =>
        `| ${script} | ![approved ${script}](approved-${script.toLowerCase()}.png) | ` +
        `![candidate ${script}](candidate-${script.toLowerCase()}.png) | ` +
        `![difference map ${script}](difference-${script.toLowerCase()}.png) |`
    )
    .join("\n");
  const changes = faces
    .map(
      (face) =>
        `| ${face.family} ${face.weight} ${face.script} | \`${face.approved_sha256}\` | ` +
        `\`${face.candidate_sha256}\` | ${face.changed ? "changed" : "unchanged"} |`
    )
    .join("\n");
  const measurements = comparisons
    .map((comparison) => {
      const bounds = comparison.bounds
        ? `${comparison.bounds.x},${comparison.bounds.y} · ${comparison.bounds.width}×${comparison.bounds.height}`
        : "none";
      return `| ${comparison.script} | ${comparison.changed_pixels.toLocaleString("en-US")} / ` +
        `${comparison.total_pixels.toLocaleString("en-US")} (${percent(comparison.changed_fraction)}) | ` +
        `${comparison.mean_changed_channel_delta.toFixed(2)} | ${comparison.maximum_channel_delta} | ${bounds} |`;
    })
    .join("\n");
  return `# Film font migration review\n\nCandidate: Fontsource ${candidateVersion}\n\n` +
    `## Frames\n\n| Script | Approved bytes | Candidate bytes | Difference map |\n` +
    `| --- | --- | --- | --- |\n${rows}\n\n` +
    `Indigo marks pixels Chromium rendered differently; the quiet approved frame remains ` +
    `underneath for context. Review line breaks, shaping, matras, diacritics, punctuation, ` +
    `weight and rhythm at full size. A difference is evidence for a person, never an automatic rejection.\n\n` +
    `## Pixel evidence\n\n| Script | Changed pixels | Mean RGB delta | Maximum delta | Bounds (x,y · w×h) |\n` +
    `| --- | ---: | ---: | ---: | --- |\n${measurements}\n\n` +
    `Measurements are exact only for the browser, platform and approved/candidate pair used for this run.\n\n` +
    `## Byte changes\n\n| Face | Approved SHA-256 | Candidate SHA-256 | Result |\n` +
    `| --- | --- | --- | --- |\n${changes}\n\n` +
    `## Decision\n\n- [ ] Approved\n- [ ] Rejected\n\nReviewer: ____________________\n\nDate: ____________________\n`;
}

export function runReview(): void {
  const candidateRoot = resolve(argument("--candidate-root"));
  const candidateVersion = argument("--candidate-version");
  const output = resolve(argument("--output"));
  if (!/^\d+\.\d+\.\d+$/.test(candidateVersion)) {
    throw new Error("candidate version must be an exact release, for example 5.4.0");
  }
  if (existsSync(output) && readdirSync(output).length > 0) {
    throw new Error(`font review output is not empty: ${output}`);
  }
  mkdirSync(output, { recursive: true });

  const approved = approvedFaces();
  const candidate = candidateFaces(candidateRoot, candidateVersion);
  const faces: ReviewFace[] = approved.map((face, index) => ({
    family: face.family,
    role: face.role,
    weight: face.weight,
    script: face.script,
    file: face.file,
    approved_sha256: face.digest,
    candidate_sha256: candidate[index]!.digest,
    changed: face.digest !== candidate[index]!.digest,
  }));
  const basenames = [
    ...renderDocuments("approved", approved, output),
    ...renderDocuments("candidate", candidate, output),
  ];
  const playwright = process.env.PLAYWRIGHT_CLI ?? join(repositoryRoot, ".venv", "bin", "playwright");
  screenshot(basenames, output, playwright);

  const comparisons = (["Latin", "Arabic", "Devanagari"] as const).map((script) => {
    const slug = script.toLowerCase();
    const approvedFile = `approved-${slug}.png`;
    const candidateFile = `candidate-${slug}.png`;
    const differenceFile = `difference-${slug}.png`;
    const compared = comparePngs(
      readFileSync(join(output, approvedFile)),
      readFileSync(join(output, candidateFile))
    );
    writeFileSync(join(output, differenceFile), compared.difference);
    return {
      script,
      approved: approvedFile,
      candidate: candidateFile,
      difference: differenceFile,
      ...compared.metrics,
    };
  });

  writeFileSync(
    join(output, "font-review.json"),
    JSON.stringify(
      {
        schema: "anuvritti.font-review.v2",
        candidate_version: candidateVersion,
        faces,
        comparisons,
      },
      null,
      2
    )
  );
  writeFileSync(join(output, "REVIEW.md"), reviewMarkdown(candidateVersion, faces, comparisons));
  for (const face of faces) {
    console.log(
      `${face.role}/${face.script} ${face.family} ${face.weight}: ` +
        `${face.approved_sha256} -> ${face.candidate_sha256} ${face.changed ? "changed" : "unchanged"}`
    );
  }
  for (const comparison of comparisons) {
    console.log(
      `${comparison.script}: ${comparison.changed_pixels}/${comparison.total_pixels} pixels ` +
        `changed (${percent(comparison.changed_fraction)})`
    );
  }
  console.log(`review ${basenames.length} stills and ${comparisons.length} difference maps at ${join(output, "REVIEW.md")}`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  runReview();
}
