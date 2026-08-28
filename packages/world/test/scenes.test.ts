/**
 * The film's scenes, held to the same rules as the interface.
 *
 * `scripts/check-scenes.ts` is the gate that reads the Python domain and the emitted CSS.
 * These are the smaller questions underneath it: does the renderer escape what a parent
 * typed, does it leave a caption alone, and does it refuse to draw what it was not given.
 */
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";

import { FRAME, SCENE_KINDS, escapeHtml, renderScene, type SceneKind } from "../scenes/scene.ts";
import { emitSceneCss, FILM_ROOT_PX } from "../scenes/css.ts";
import { FILM_FONTS, FILM_SCRIPTS, unsupportedFilmCodepoints } from "../scenes/fonts.ts";
import {
  approveRenderRequirements,
  assertInstalledFilmFontDigests,
} from "../scenes/preparation.ts";
import { encodePng } from "../scripts/png-difference.ts";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const domain = readFileSync(
  join(root, "..", "..", "src", "anuvritti", "domain", "film.py"),
  "utf8"
);

describe("the film and the domain are the same six scenes", () => {
  test("every kind the domain can produce has a layout", () => {
    const start = domain.indexOf("class SceneKind(StrEnum):");
    assert.ok(start > 0, "SceneKind is no longer where this test looks for it");
    const block = domain.slice(start, domain.indexOf("\nclass ", start + 1));
    const kinds = [...block.matchAll(/^ {4}[A-Z_]+ = "([A-Z_]+)"$/gm)].map((m) => m[1]!);

    assert.deepEqual([...kinds].sort(), [...SCENE_KINDS].sort());
  });

  test("the frame is the frame the compiler declares", () => {
    assert.match(domain, new RegExp(`_FRAME_WIDTH = ${FRAME.width}$`, "m"));
    assert.match(domain, new RegExp(`_FRAME_HEIGHT = ${FRAME.height}$`, "m"));
    assert.match(domain, new RegExp(`_FPS = ${FRAME.fps}$`, "m"));
  });
});

describe("what a parent typed is text, never markup", () => {
  test("a heading with a bracket in it does not become an element", () => {
    const html = renderScene({
      id: "s1",
      kind: "MOMENT",
      heading: '<script>alert("hi")</script>',
    });
    assert.ok(!html.includes("<script>"));
    assert.ok(html.includes("&lt;script&gt;"));
  });

  test("an apostrophe survives as an apostrophe", () => {
    assert.equal(escapeHtml("Papa's"), "Papa&#39;s");
  });
});

describe("a caption is passed through, not processed", () => {
  const MARKED = "[read by a machine] Everything here happened. Nothing here was invented.";

  test("the machine's mark reaches the picture intact", () => {
    for (const kind of SCENE_KINDS) {
      const html = renderScene({ id: "s1", kind, heading: "a heading", narration: MARKED });
      assert.ok(html.includes(MARKED), `${kind} altered the caption`);
    }
  });

  test("a scene with no narration has no caption band at all", () => {
    const html = renderScene({ id: "s1", kind: "MOMENT", heading: "a heading" });
    assert.ok(!html.includes("caption"));
  });
});

describe("nothing is drawn that was not given", () => {
  test("no picture means no image element and no placeholder", () => {
    for (const kind of SCENE_KINDS) {
      const html = renderScene({ id: "s1", kind, heading: "a heading" });
      assert.ok(!html.includes("<img"), `${kind} invented a picture`);
    }
  });

  test("a picture is referenced exactly as it was handed over", () => {
    const html = renderScene({
      id: "s1",
      kind: "MOMENT",
      heading: "a heading",
      picture: "media/med-0001.jpg",
    });
    assert.ok(html.includes('src="media/med-0001.jpg"'));
  });
});

describe("the document a renderer opens", () => {
  test("commits to one theme rather than inheriting the render host's", () => {
    for (const kind of SCENE_KINDS) {
      const html = renderScene({ id: "s1", kind, heading: "a heading" });
      assert.ok(html.includes('data-theme="light"'), `${kind} lets the host decide`);
    }
  });

  test("carries the scene id, so a frame can be traced back to what it claims", () => {
    const html = renderScene({ id: "moment-mom-7", kind: "MOMENT", heading: "a heading" });
    assert.ok(html.includes('id="moment-mom-7"'));
  });

  test("links the app's own stylesheet rather than restating it", () => {
    const html = renderScene({ id: "s1", kind: "OPENING", heading: "a heading" });
    assert.ok(html.includes('href="world.css"'));
    assert.ok(!html.includes("<style"));
  });

  test("can carry the same styles inline for a browser with no base URL", () => {
    const html = renderScene(
      { id: "s1", kind: "OPENING", heading: "a heading" },
      { inlineCss: [":root { --w-color-ground: white; }", ".frame { display: grid; }"] }
    );
    assert.ok(html.includes("<style>:root"));
    assert.ok(html.includes("<style>.frame"));
    assert.ok(!html.includes("<link"));
  });

  test("lets each saved line establish its own direction", () => {
    const html = renderScene({
      id: "s1",
      kind: "MOMENT",
      heading: "أول مرة نزل فيها وحده",
      body: "पहली बार वह अकेले फिसला",
    });
    assert.match(html, /<h1[^>]+dir="auto"/);
    assert.match(html, /<p class="quiet lead measure" dir="auto"/);
  });
});

describe("the film's offline writing systems", () => {
  test("declares Latin, Arabic and Devanagari and bundles display and body faces", () => {
    assert.deepEqual(
      FILM_SCRIPTS.map((script) => script.name),
      ["Latin", "Arabic", "Devanagari"]
    );
    for (const script of FILM_SCRIPTS) {
      assert.ok(FILM_FONTS.some((font) => font.script === script.name && font.role === "display"));
      assert.ok(FILM_FONTS.some((font) => font.script === script.name && font.role === "body"));
    }
  });

  test("accepts real family text in every declared script", () => {
    assert.deepEqual(unsupportedFilmCodepoints("Aarav’s first slide — 2026"), []);
    assert.deepEqual(unsupportedFilmCodepoints("أول مرة نزل فيها وحده"), []);
    assert.deepEqual(unsupportedFilmCodepoints("पहली बार वह अकेले फिसला"), []);
  });

  test("names an unbundled glyph instead of silently borrowing a host font", () => {
    assert.deepEqual(unsupportedFilmCodepoints("家"), ["U+5BB6"]);
  });

  test("approves only this exact pinned world bundle before setup fetches it", () => {
    const font_packages = Object.fromEntries(
      FILM_FONTS.map((face) => [face.package, face.version])
    );
    const requirements = {
      schema: "anuvritti.render-requirements.v1",
      scripts: ["Arabic"],
      world: { package: "@anuvritti/world", version: "0.1.0", font_packages },
    };
    assert.deepEqual(
      approveRenderRequirements(requirements, {
        name: "@anuvritti/world",
        version: "0.1.0",
      }).scripts,
      ["Arabic"]
    );
    assert.throws(
      () =>
        approveRenderRequirements(
          { ...requirements, world: { ...requirements.world, font_packages: { "host-font": "latest" } } },
          { name: "@anuvritti/world", version: "0.1.0" }
        ),
      /approved pinned font bundle exactly/
    );
  });

  test("approves the bytes of every bundled face, not only its package name", () => {
    const installed = Object.fromEntries(FILM_FONTS.map((face) => [face.file, face.sha256]));

    assert.doesNotThrow(() => assertInstalledFilmFontDigests(installed));
    assert.ok(FILM_FONTS.every((face) => /^[0-9a-f]{64}$/.test(face.sha256)));
    assert.throws(
      () =>
        assertInstalledFilmFontDigests({
          ...installed,
          [FILM_FONTS[0].file]: "0".repeat(64),
        }),
      new RegExp(`installed font bytes are not approved: ${FILM_FONTS[0].file}`)
    );
  });

  test("reviews approved and candidate bytes as six multilingual stills", () => {
    const temporary = mkdtempSync(join(tmpdir(), "anuvritti-font-review-"));
    const output = join(temporary, "review");
    const fakePlaywright = join(temporary, "playwright");
    const fixture = join(temporary, "frame.png");
    writeFileSync(
      fixture,
      encodePng({ width: 2, height: 1, pixels: Uint8Array.from([19, 27, 42, 255, 249, 248, 243, 255]) })
    );
    writeFileSync(
      fakePlaywright,
      "#!/bin/sh\nfor last do :; done\ncp \"$PLAYWRIGHT_FIXTURE\" \"$last\"\n"
    );
    chmodSync(fakePlaywright, 0o700);
    try {
      const reviewed = spawnSync(
        process.execPath,
        [
          join(root, "scripts", "review-film-fonts.ts"),
          "--candidate-root",
          join(root, "node_modules"),
          "--candidate-version",
          "5.3.0",
          "--output",
          output,
        ],
        {
          encoding: "utf8",
          env: { ...process.env, PLAYWRIGHT_CLI: fakePlaywright, PLAYWRIGHT_FIXTURE: fixture },
        }
      );
      assert.equal(reviewed.status, 0, reviewed.stderr);
      const receipt = JSON.parse(readFileSync(join(output, "font-review.json"), "utf8")) as {
        schema: string;
        faces: { approved_sha256: string; candidate_sha256: string }[];
        comparisons: { script: string; changed_pixels: number; bounds: unknown }[];
      };
      assert.equal(receipt.schema, "anuvritti.font-review.v2");
      assert.equal(receipt.faces.length, FILM_FONTS.length);
      assert.ok(
        receipt.faces.every((face) => face.approved_sha256 === face.candidate_sha256)
      );
      for (const state of ["approved", "candidate"]) {
        for (const script of ["latin", "arabic", "devanagari"]) {
          assert.ok(readFileSync(join(output, `${state}-${script}.png`)).byteLength > 0);
        }
      }
      assert.deepEqual(
        receipt.comparisons.map((comparison) => comparison.script),
        ["Latin", "Arabic", "Devanagari"]
      );
      assert.ok(receipt.comparisons.every((comparison) => comparison.changed_pixels === 0));
      assert.ok(receipt.comparisons.every((comparison) => comparison.bounds === null));
      for (const script of ["latin", "arabic", "devanagari"]) {
        assert.ok(readFileSync(join(output, `difference-${script}.png`)).byteLength > 0);
      }
      const sheet = readFileSync(join(output, "REVIEW.md"), "utf8");
      assert.match(sheet, /- \[ \] Approved/);
      assert.match(sheet, /Approved SHA-256.*Candidate SHA-256/);
      assert.match(sheet, /Difference map/);
      assert.match(sheet, /Devanagari.*0 \/ 2 \(0\.0000%\)/);
    } finally {
      rmSync(temporary, { recursive: true, force: true });
    }
  });
});

describe("the film's stylesheet", () => {
  const css = emitSceneCss();
  const code = css.replace(/\/\*[\s\S]*?\*\//g, "");

  test("names no colour of its own", () => {
    assert.equal(code.match(/#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/g), null);
  });

  test("holds still", () => {
    assert.equal(code.match(/@keyframes|\banimation\b|\btransition\b/g), null);
  });

  test("scales the type by moving the root, so the ratios stay the app's", () => {
    assert.ok(code.includes(`font-size: ${FILM_ROOT_PX}px`));
    assert.equal(FILM_ROOT_PX % 16, 0);
  });

  test("draws every kind it claims to", () => {
    for (const kind of SCENE_KINDS) {
      const selector = `.${(kind as SceneKind).toLowerCase().replace(/_/g, "-")}`;
      const html = renderScene({ id: "s1", kind, heading: "a heading" });
      assert.ok(html.includes(selector.slice(1)), `${kind} has no class on its frame`);
    }
  });
});
