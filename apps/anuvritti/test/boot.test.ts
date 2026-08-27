/**
 * TASK-713 — what a fresh install does before anything can lie to it.
 *
 * Three things have to be true the first time the app opens on a phone that has never
 * been paired, and none of them were:
 *
 * 1. The empty home must never appear. "Nothing today. That's normal." is a true and
 *    finished state *for a paired family*; on an unpaired phone it is the app claiming
 *    to have looked. It had not — every request was answering `UNAUTHENTICATED`.
 * 2. The way to `/pair` has to exist. Nothing routed there.
 * 3. Every typeface a screen asks for has to have been loaded, or the words render in
 *    whatever face the platform felt like.
 *
 * The gate itself is a pure function, so it is tested here. Whether the layout actually
 * uses it is read off the source, which is the only way to check a view layer that needs
 * a device to run.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { HOME, PAIR, gateFor, showsHome, showsPairing } from "../src/session/gate.ts";
import { FONT } from "../src/world.ts";

const layout = readFileSync(new URL("../app/_layout.tsx", import.meta.url), "utf8");
const pairScreen = readFileSync(new URL("../app/pair.tsx", import.meta.url), "utf8");

/** Source with comments removed, so prose about a mistake never trips the check for it. */
function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

/** Every `world.font.<face>` a screen or component actually asks for. */
function facesInUse(): ReadonlySet<string> {
  const files = [
    "../app/index.tsx",
    "../app/pair.tsx",
    "../app/vault.tsx",
    "../src/components/Spark.tsx",
    "../src/components/VoiceNote.tsx",
    "../src/components/HoldToTalk.tsx",
  ];
  const used = new Set<string>();
  for (const file of files) {
    const source = readFileSync(new URL(file, import.meta.url), "utf8");
    for (const match of source.matchAll(/world\.font\.(\w+)/g)) used.add(match[1]!);
  }
  return used;
}

describe("the gate", () => {
  it("sends a phone that has never been paired to the pairing screen", () => {
    assert.equal(gateFor(false), "pair");
    assert.ok(showsPairing(gateFor(false)));
  });

  it("sends a phone that holds a token home", () => {
    assert.equal(gateFor(true), "home");
    assert.ok(showsHome(gateFor(true)));
  });

  it("shows neither while it does not yet know", () => {
    // The whole of "no flash of the empty home": before the keychain has answered there
    // is no answer to show, and an empty home is not a neutral thing to show meanwhile.
    assert.equal(gateFor(null), "waiting");
    assert.equal(showsHome(gateFor(null)), false);
    assert.equal(showsPairing(gateFor(null)), false);
  });

  it("never shows both at once", () => {
    for (const paired of [null, true, false] as const) {
      const gate = gateFor(paired);
      assert.ok(!(showsHome(gate) && showsPairing(gate)), `both shown for ${String(paired)}`);
    }
  });
});

describe("the layout is the gate", () => {
  it("asks the gate rather than deciding for itself", () => {
    assert.match(layout, /gateFor|showsHome|showsPairing/);
  });

  it("guards the home routes, so the empty home cannot render unpaired", () => {
    // `Stack.Protected` takes the screen out of the navigation tree rather than
    // redirecting away from it. A redirect renders the wrong screen first; this cannot.
    assert.match(layout, /Stack\.Protected/);
    assert.match(layout, /guard=\{showsHome\(/);
    assert.match(layout, /guard=\{showsPairing\(/);
  });

  it("holds the first frame on the ground colour until pairing is known", () => {
    assert.match(layout, /color\.ground/);
  });
});

describe("pairing lands on the home it just earned", () => {
  it("replaces rather than pushes, so there is no way back to the pairing screen", () => {
    assert.match(pairScreen, /replace\(\s*HOME\s*\)|replace\("\/"\)/);
    assert.ok(!/router\.push/.test(pairScreen), "pairing pushed instead of replacing");
  });

  it("tells the app it is paired before it navigates", () => {
    // Navigating first would land on a home whose gate still said "unpaired", and the
    // guard would take it straight back to /pair.
    const replaceAt = pairScreen.search(/router\.replace/);
    const refreshAt = pairScreen.search(/refreshPairing\(\)/);
    assert.ok(refreshAt >= 0, "the pair screen never refreshes the pairing state");
    assert.ok(refreshAt < replaceAt, "it navigated before it knew it was paired");
  });
});

describe("the routes are named once", () => {
  it("says where home and pairing are, so no screen spells them itself", () => {
    assert.equal(HOME, "/");
    assert.equal(PAIR, "/pair");
  });
});

describe("the typefaces", () => {
  it("loads every face a screen asks for", () => {
    for (const face of facesInUse()) {
      const family = FONT[face as keyof typeof FONT];
      assert.ok(family, `world.font.${face} is not a face`);
      assert.ok(
        layout.includes(family),
        `${family} is used on a screen and never loaded in _layout`
      );
    }
  });

  it("imports the faces under the names the packages actually export", () => {
    // `useIBMPlexMono_400Regular` is not an export of @expo-google-fonts/ibm-plex-mono
    // and never was. It named nothing, loaded nothing, and cost the app its mono face.
    assert.ok(
      !/\buse[A-Z]\w*_\d{3}\w+/.test(withoutComments(layout)),
      "a font is imported under a `useX_400Regular` name no font package exports"
    );
  });
});
