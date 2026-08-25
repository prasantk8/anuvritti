/**
 * The design language, held to its own rules.
 *
 * These are the pixel counterpart of `tests/constitution`. If one fails, the correct
 * response is usually not to change the test - it is to ask whether the interface just
 * crossed a line the PRD said it would not cross.
 */
import { test, describe } from "node:test";
import assert from "node:assert/strict";

import { COLORS, ROLES, tokens, palette, MOTION_CEILING_MS, MOTION_CEILING_EXEMPT } from "../src/tokens.ts";
import { DURATION, ELEVATION, SPACE, FONTS } from "../src/scale.ts";
import { emitCss } from "../src/css.ts";
import { chroma, contrast, hsl } from "./contrast.ts";

const THEMES = ["light", "dark"] as const;

describe("every token is well formed", () => {
  test("names are unique", () => {
    const names = COLORS.map((c) => c.name);
    assert.equal(new Set(names).size, names.length);
  });

  test("both themes are defined for every colour, as six-digit hex", () => {
    for (const c of COLORS) {
      for (const theme of THEMES) {
        assert.match(c[theme], /^#[0-9A-F]{6}$/i, `${c.name}.${theme}`);
      }
    }
  });

  test("every colour states what it is for", () => {
    for (const c of COLORS) {
      assert.ok(c.meaning.length > 30, `${c.name} has no stated meaning`);
      assert.ok(ROLES.includes(c.role), `${c.name} has role ${c.role}`);
    }
  });

  test("every font role explains when to reach for it", () => {
    for (const f of FONTS) {
      assert.ok(f.meaning.length > 30, `${f.name}`);
      assert.ok(f.stack.includes(","), `${f.name} has no fallback stack`);
    }
  });
});

describe("legibility, in both themes", () => {
  test("text tokens meet their stated contrast on every ground they sit on", () => {
    const failures: string[] = [];
    for (const c of COLORS) {
      if (!c.readableOn) continue;
      for (const theme of THEMES) {
        const p = palette(theme);
        for (const groundName of c.readableOn) {
          const ground = p[groundName];
          assert.ok(ground, `${c.name} names an unknown ground ${groundName}`);
          const ratio = contrast(c[theme], ground);
          if (ratio < (c.minContrast ?? 4.5)) {
            failures.push(
              `${c.name} on ${groundName} (${theme}): ${ratio.toFixed(2)} < ${c.minContrast}`
            );
          }
        }
      }
    }
    assert.deepEqual(failures, [], `contrast failures:\n  ${failures.join("\n  ")}`);
  });

  test("elevation is themed, because a shadow is made of colour", () => {
    for (const [name, e] of Object.entries(ELEVATION)) {
      if (name === "flat") continue;
      assert.notEqual(e.light, e.dark, `elevation.${name} is invisible in one of the two themes`);
      assert.ok(e.dark.includes("rgba(0, 0, 0"), `elevation.${name} must use true black on a dark ground`);
    }
  });

  test("neither theme is a naive inversion of the other", () => {
    for (const c of COLORS) {
      assert.notEqual(c.light.toUpperCase(), c.dark.toUpperCase(), `${c.name} is theme-blind`);
    }
  });
});

describe("PRD 47 - the constitution, in colour", () => {
  test("red belongs only to what cannot be undone", () => {
    const reddish = COLORS.filter((c) =>
      THEMES.some((t) => {
        const { h } = hsl(c[t]);
        return chroma(c[t]) > 0.25 && (h <= 18 || h >= 344);
      })
    );
    assert.deepEqual(
      reddish.map((c) => c.name),
      ["unmade"],
      "PRD 8.5: urgency colour is reserved for destructive actions. Lateness is not urgent, and a child is never an error state."
    );
  });

  test("the voice colour is rationed to the voice role", () => {
    const saffron = COLORS.filter((c) => c.name.startsWith("saffron"));
    assert.ok(saffron.length > 0);
    for (const c of saffron) {
      assert.equal(c.role, "voice", `${c.name} must mean a person spoke, or it means nothing`);
    }
    // And nothing outside the voice role may occupy saffron's hue band at strength.
    const trespassers = COLORS.filter(
      (c) =>
        c.role !== "voice" &&
        THEMES.some((t) => {
          const { h } = hsl(c[t]);
          return chroma(c[t]) > 0.25 && h > 25 && h < 55;
        })
    );
    assert.deepEqual(trespassers.map((c) => c.name), []);
  });

  test("the palette has no token for lateness, streaks or scoring", () => {
    const forbidden = ["overdue", "late", "streak", "score", "badge", "warning", "danger", "alert", "success"];
    for (const c of COLORS) {
      for (const word of forbidden) {
        assert.ok(!c.name.includes(word), `token ${c.name} names a concept PRD 47 forbids`);
      }
    }
  });
});

describe("PRD 56 - restraint, as a scale", () => {
  test("space is a scale; nothing is off it", () => {
    for (const [name, value] of Object.entries(SPACE)) {
      assert.ok(value % 4 === 0 || value === 2, `space.${name} = ${value} is off the 4px scale`);
    }
  });

  test("motion has a ceiling, and exactly one documented exception", () => {
    for (const [name, ms] of Object.entries(DURATION)) {
      if ((MOTION_CEILING_EXEMPT as readonly string[]).includes(name)) continue;
      assert.ok(ms <= MOTION_CEILING_MS, `duration.${name} = ${ms}ms exceeds the ceiling`);
    }
    assert.equal(MOTION_CEILING_EXEMPT.length, 1, "exceptions are not a growing list");
  });

  test("the touch target is never below 44px, including on the child surface", () => {
    assert.ok(tokens.layout.touch >= 44);
  });
});

describe("the emitted CSS survives all three viewer states", () => {
  const css = emitCss();
  // Everything made of colour: the palette, and elevation, which is a coloured shadow.
  const names = [
    ...COLORS.map((c) => `--w-color-${c.name}`),
    ...Object.keys(ELEVATION).map((k) => `--w-elevation-${k}`),
  ];

  test("the bare :root carries the complete light palette", () => {
    const root = css.slice(css.indexOf(":root {"), css.indexOf("@media"));
    for (const n of names) assert.ok(root.includes(n), `${n} missing from :root`);
  });

  test("no colour is defined only inside a media query or a [data-theme] block", () => {
    // The classic unreadable-page bug: a token whose sole definition sits behind a
    // guard means the un-stamped system-default viewer never receives it.
    const beforeAnyGuard = css.slice(0, css.indexOf("@media"));
    const orphans = names.filter((n) => !beforeAnyGuard.includes(n));
    assert.deepEqual(orphans, []);
  });

  test("dark is reachable both by system preference and by explicit choice", () => {
    assert.ok(css.includes('@media (prefers-color-scheme: dark)'));
    assert.ok(css.includes(':root:not([data-theme="light"])'), "an explicit light choice must beat a dark OS");
    assert.ok(css.includes(':root[data-theme="dark"]'), "the toggle must win in the other direction");
    const darkBlocks = css.split(":root").filter((b) => b.includes("--w-color-ground: #12151C"));
    assert.equal(darkBlocks.length, 2, "the dark palette must appear in both guards");
  });

  test("the ground is painted explicitly, so the page never borrows the host's theme", () => {
    assert.match(css, /html \{\s*background: var\(--w-color-ground\);/);
    assert.match(css, /body \{[^}]*background: var\(--w-color-ground\);/);
  });

  test("reduced motion is honoured for every duration token", () => {
    const reduced = css.slice(css.indexOf("prefers-reduced-motion"));
    for (const k of Object.keys(DURATION)) {
      assert.ok(reduced.includes(`--w-duration-${k}: 1ms;`), `duration.${k} ignores reduced motion`);
    }
  });

  test("the font request is a valid URL, with no raw spaces in a family name", () => {
    const href = css.match(/@import url\("([^"]+)"\)/)?.[1];
    assert.ok(href, "no font import emitted");
    assert.ok(!href.includes(" "), `raw space in font URL silently kills the request: ${href}`);
    for (const f of FONTS) {
      if (!f.webfont) continue;
      assert.ok(href.includes(f.webfont.family.replace(/ /g, "+")), `${f.name} not requested`);
    }
  });

  test("only Google Fonts is referenced; the CSP admits no other host", () => {
    const urls = css.match(/url\(["']?([^"')]+)/g) ?? [];
    for (const u of urls) {
      assert.ok(u.includes("fonts.googleapis.com"), `external asset host: ${u}`);
    }
  });
});
