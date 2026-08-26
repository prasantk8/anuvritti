/**
 * The film's drift detector (TASK-708).
 *
 * `check-specimen` proves the design language documents itself. This proves the *film* is
 * made of that language rather than made to look like it, and it does so by reading the two
 * files that would otherwise drift apart in silence: the Python domain that decides what a
 * scene is, and the CSS the app is drawn from.
 *
 * Eight things, each of which has a way of going wrong that no test would otherwise catch:
 *
 *   1. every `SceneKind` in the Python domain has a layout here - a kind nobody drew comes
 *      out as an empty frame in a family's film, not as a red test;
 *   2. the frame size the scenes are cut to is the frame size the compiler declares;
 *   3. no scene stylesheet names a colour, a font or a size of its own;
 *   4. every custom property the scenes reference exists in the emitted `world.css`;
 *   5. nothing animates - a screenshot of a moving page is a coin toss;
 *   6. no external asset host but the one the CSP admits;
 *   7. a caption renders exactly as it was given, mark and all;
 *   8. a scene with no picture contains no picture.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { emitSceneCss, FILM_ROOT_PX } from "../scenes/css.ts";
import { FRAME, renderScene, SCENE_KINDS, type SceneKind } from "../scenes/scene.ts";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const repo = join(root, "..", "..");
const worldCss = readFileSync(join(root, "dist", "world.css"), "utf8");
const scenesCss = emitSceneCss();
// Comments in this file are prose about why a rule exists, and prose mentions the very words
// the rules forbid. Everything mechanical below reads the declarations, not the commentary.
const scenesCode = scenesCss.replace(/\/\*[\s\S]*?\*\//g, "");
const domain = readFileSync(join(repo, "src", "anuvritti", "domain", "film.py"), "utf8");

const problems: string[] = [];

/** The members of a Python `StrEnum`, read out of the source rather than trusted. */
function pythonEnumMembers(source: string, name: string): string[] {
  const start = source.indexOf(`class ${name}(StrEnum):`);
  if (start < 0) return [];
  const rest = source.slice(start + 1);
  const end = rest.indexOf("\nclass ");
  const block = end < 0 ? rest : rest.slice(0, end);
  return [...block.matchAll(/^ {4}([A-Z_]+) = "([A-Z_]+)"$/gm)].map((m) => m[2]!);
}

function pythonConstant(source: string, name: string): number | null {
  const found = source.match(new RegExp(`^${name} = (\\d+)$`, "m"));
  return found ? Number(found[1]) : null;
}

// 1. Kind parity with the domain.
const domainKinds = pythonEnumMembers(domain, "SceneKind");
if (domainKinds.length === 0) {
  problems.push("could not read SceneKind out of the Python domain - this check is not running");
}
for (const kind of domainKinds) {
  if (!SCENE_KINDS.includes(kind as SceneKind)) {
    problems.push(`the film can contain a ${kind} scene, and nothing here draws one`);
  }
}
for (const kind of SCENE_KINDS) {
  if (domainKinds.length && !domainKinds.includes(kind)) {
    problems.push(`there is a layout for ${kind}, which the domain no longer has`);
  }
}

// 2. Frame parity. Scenes cut to the wrong size render letterboxed or cropped.
for (const [name, ours] of [
  ["_FRAME_WIDTH", FRAME.width],
  ["_FRAME_HEIGHT", FRAME.height],
  ["_FPS", FRAME.fps],
] as const) {
  const theirs = pythonConstant(domain, name);
  if (theirs !== null && theirs !== ours) {
    problems.push(`${name} is ${theirs} in the domain and ${ours} in the scenes`);
  }
}

// 3. The scenes name nothing of their own.
for (const literal of scenesCode.match(/#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/g) ?? []) {
  problems.push(`the scenes name a colour of their own: ${literal}`);
}
const ALLOWED_PIXELS = new Set([FRAME.width, FRAME.height, FILM_ROOT_PX]);
for (const [, value] of scenesCode.matchAll(/\b(\d+(?:\.\d+)?)px\b/g)) {
  if (!ALLOWED_PIXELS.has(Number(value))) {
    problems.push(`the scenes hard-code ${value}px, which is not on the space scale`);
  }
}
for (const [, property, value] of scenesCode.matchAll(
  /\b(font-family|font-size|font-weight):([^;]+);/g
)) {
  // The film's root size is the one declared exception, and it is why the type tokens
  // scale together instead of each being re-picked for a 1920-wide frame.
  if (property === "font-size" && value!.trim() === `${FILM_ROOT_PX}px`) continue;
  if (!value!.includes("var(")) {
    problems.push(`the scenes set ${property} without a token: ${value!.trim()}`);
  }
}

// 4. No dangling references.
const declared = new Set(worldCss.match(/--w-[a-z0-9-]+(?=\s*:)/g) ?? []);
for (const [, name] of scenesCode.matchAll(/var\((--w-[a-z0-9-]+)\)/g)) {
  if (!declared.has(name!)) {
    problems.push(`the scenes reference ${name}, which world.css does not define`);
  }
}

// 5. A frame holds still.
for (const moving of scenesCode.match(/@keyframes|\banimation\b|\btransition\b/g) ?? []) {
  problems.push(`the scenes use ${moving}, and a screenshot of a moving page is a coin toss`);
}

// ------------------------------------------------------------------ the documents
const CAPTION = "[read by a machine] Everything here happened. Nothing here was invented.";

for (const kind of SCENE_KINDS) {
  const html = renderScene({
    id: `sample-${kind.toLowerCase()}`,
    kind,
    heading: "counting to twenty in the bath",
    body: "Six minutes, most of it wrong, none of it corrected.",
    narration: CAPTION,
  });

  // 6. One font host, and no script anywhere.
  for (const src of html.match(/(?:src|href)="(https?:\/\/[^"]+)"/g) ?? []) {
    if (!src.includes("fonts.googleapis.com") && !src.includes("fonts.gstatic.com")) {
      problems.push(`${kind}: external asset host ${src}`);
    }
  }
  if (/<script/i.test(html)) problems.push(`${kind}: a still frame does not need a script`);
  if (/ style="/i.test(html)) problems.push(`${kind}: an inline style is a token that got away`);

  // 7. The caption arrives marked and leaves marked.
  if (!html.includes(CAPTION)) {
    problems.push(`${kind}: the caption was not rendered exactly as it was given`);
  }

  // 8. Nothing drawn that was not given.
  if (html.includes("<img")) {
    problems.push(`${kind}: a scene with no picture drew one anyway`);
  }
  if (/@keyframes|animation:|transition:/.test(html)) {
    problems.push(`${kind}: the document itself animates`);
  }
}

// 9. The seam. `renderScene` keys off the scene kind, and the kind reaches a renderer through
//    the compiler's timeline. A rename on the Python side is silent - every frame still
//    renders, each one as the default layout - so the field is checked by name.
const compiler = readFileSync(
  join(repo, "src", "anuvritti", "adapters", "film", "filmkit_compiler.py"),
  "utf8"
);
if (!compiler.includes("type=scene.kind.value")) {
  problems.push(
    "the compiler no longer labels timeline scenes with their kind, so every frame would " +
      "draw as the default layout without anything failing"
  );
}

// The picture path is used, and only when there is a picture.
const withPicture = renderScene({
  id: "moment-1",
  kind: "MOMENT",
  heading: "first time down the slide alone",
  picture: "media/med-0001.jpg",
});
if (!withPicture.includes('src="media/med-0001.jpg"')) {
  problems.push("a scene with a picture did not draw it");
}

if (problems.length) {
  console.error(`scenes check failed (${problems.length}):`);
  for (const p of problems) console.error(`  - ${p}`);
  process.exit(1);
}
console.log(
  `scenes ok - ${SCENE_KINDS.length} kinds drawn, ${FRAME.width}x${FRAME.height} to match the ` +
    `compiler, every value a token, nothing moving`
);
