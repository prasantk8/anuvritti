/**
 * A film scene, drawn out of the same tokens the app is drawn from (PRD 56).
 *
 * filmkit renders a film by holding one still frame per scene and screenshotting it in
 * Chromium. That makes a scene an ordinary HTML document, which is the whole opportunity:
 * the film does not need to be *styled to resemble* the app, it can be built out of the
 * same material. `world.css` is the same file both consume, so a colour that changes in
 * `src/color.ts` changes in the app and in every film compiled after it, and there is no
 * second place for the visual language to live and drift.
 *
 * Four decisions here are not stylistic, and each has a check behind it in
 * `scripts/check-scenes.ts`:
 *
 * **The kinds come from the domain.** `SceneKind` here is the same closed set as the Python
 * `SceneKind`, and the check reads the Python file to prove it. A film with a kind nobody
 * drew renders as a blank frame - which is exactly the failure that reaches a family rather
 * than a test.
 *
 * **A frame holds still.** No animation, no transition, no keyframes anywhere in a scene.
 * A screenshot of a moving page captures whatever moment the screenshot happened to land
 * on, so an animated scene is a scene that renders differently on a slower machine.
 *
 * **A film is one theme, always.** The document stamps `data-theme="light"` rather than
 * letting `prefers-color-scheme` decide, because the machine that draws the film is a
 * headless browser whose colour preference is an accident of how it was launched. A family
 * film should not come out on a black ground because a render host was configured at
 * midnight.
 *
 * **Nothing is drawn that was not given.** A scene with no picture has no `<img>` in it at
 * all - no placeholder, no stock image, no illustration standing in for a photograph
 * nobody took. Same rule as the compiler's: the film shows what exists.
 */

/** The same six kinds as `anuvritti.domain.film.SceneKind`, checked against it at build. */
export const SCENE_KINDS = [
  "OPENING",
  "SPARK",
  "MOMENT",
  "PROMISE_KEPT",
  "VOICE",
  "LITTLE_THING",
  "CLOSING",
] as const;

export type SceneKind = (typeof SCENE_KINDS)[number];

/** The frame the Python compiler declares. `check-scenes` proves these still agree. */
export const FRAME = { width: 1920, height: 1080, fps: 30 } as const;

export interface SceneInput {
  readonly id: string;
  readonly kind: SceneKind;
  /** The one sentence a person actually wrote: a Spark's title, a year, a count. */
  readonly heading: string;
  /** A parent's reflection, or a date range. Optional, and often absent. */
  readonly body?: string;
  /**
   * The caption, exactly as the compiler produced it.
   *
   * It arrives already marked - a line a machine read carries `[read by a machine]` from
   * `SceneVoice.caption` - and this module renders it verbatim. Nothing here parses it,
   * shortens it or strips the mark, because a renderer that "tidies" a caption is a
   * renderer that removes a disclosure.
   */
  readonly narration?: string;
  /** A path into the exported `media/` folder. Absent means there is no picture. */
  readonly picture?: string;
}

const ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ESCAPES[c]!);
}

function line(text: string | undefined, className: string): string {
  if (!text) return "";
  return `<p class="${className}" dir="auto">${escapeHtml(text)}</p>`;
}

/** The picture, whole. `contain` rather than `cover` - see the note in `emitSceneCss`. */
function picture(scene: SceneInput): string {
  if (!scene.picture) return "";
  return `<figure class="picture"><img src="${escapeHtml(scene.picture)}" alt=""></figure>`;
}

function caption(scene: SceneInput): string {
  if (!scene.narration) return "";
  return `<footer class="caption"><p dir="auto">${escapeHtml(scene.narration)}</p></footer>`;
}

/** A label in tracked uppercase. Used for the two things a viewer should be told, not sold. */
function label(text: string): string {
  return `<p class="label">${escapeHtml(text)}</p>`;
}

function body(scene: SceneInput): string {
  switch (scene.kind) {
    case "OPENING":
      return `<div class="stage centred">
        <h1 class="display name" dir="auto">${escapeHtml(scene.heading)}</h1>
        <hr class="thread">
        ${line(scene.body, "quiet lead")}
      </div>`;

    case "CLOSING":
      return `<div class="stage centred">
        <h1 class="display year" dir="auto">${escapeHtml(scene.heading)}</h1>
        <hr class="thread">
        ${line(scene.body, "quiet lead measure")}
      </div>`;

    case "VOICE":
      // No waveform. A drawn waveform that is not this recording's amplitude is a
      // decoration pretending to be data, in a product whose entire claim is that it
      // does not do that. A thread and a plain label say the true thing instead.
      return `<div class="stage centred">
        ${label("recorded")}
        <h1 class="display chapter measure" dir="auto">${escapeHtml(scene.heading)}</h1>
        <hr class="thread short">
        ${line(scene.body, "quiet lead measure")}
      </div>`;

    case "LITTLE_THING":
      return `<div class="stage centred wash">
        ${label("a little thing")}
        <h1 class="display year measure" dir="auto">${escapeHtml(scene.heading)}</h1>
        ${line(scene.body, "quiet lead measure")}
      </div>`;

    default: {
      // SPARK and MOMENT. With a photograph the frame splits; without one the words hold
      // the frame on their own, which is a real state and not a degraded one.
      const split = scene.picture ? "split" : "centred";
      return `<div class="stage ${split}">
        ${picture(scene)}
        <div class="words">
          <h1 class="display chapter" dir="auto">${escapeHtml(scene.heading)}</h1>
          ${line(scene.body, "quiet lead measure")}
        </div>
      </div>`;
    }
  }
}

export interface RenderOptions {
  /** Relative hrefs, so a scene folder can be opened from anywhere including a file URL. */
  readonly worldCss?: string;
  readonly sceneCss?: string;
  /** Complete offline renders carry their CSS inside the document. */
  readonly inlineCss?: readonly string[];
}

export function renderScene(scene: SceneInput, options: RenderOptions = {}): string {
  const world = options.worldCss ?? "world.css";
  const scenes = options.sceneCss ?? "scenes.css";
  const styles = options.inlineCss
    ? options.inlineCss.map((css) => `<style>${css}</style>`).join("\n")
    : `<link rel="stylesheet" href="${escapeHtml(world)}">\n<link rel="stylesheet" href="${escapeHtml(scenes)}">`;
  return `<!doctype html>
<html lang="und" data-theme="light">
<head>
<meta charset="utf-8">
<title>${escapeHtml(scene.id)}</title>
${styles}
</head>
<body>
<main class="frame ${scene.kind.toLowerCase().replace(/_/g, "-")}" id="${escapeHtml(scene.id)}">
${body(scene)}
${caption(scene)}
</main>
</body>
</html>
`;
}
