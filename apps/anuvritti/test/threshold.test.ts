/**
 * TASK-513 — the route graph, and what a revoked token means.
 *
 * The bug this file exists for was not in any screen. `app/pair.tsx` was written, reviewed
 * and correct; nothing anywhere pointed at it. A phone that had never paired opened Today,
 * made two calls that came back 401, and said "Nothing today. That's normal." to somebody
 * who did not yet have a family on that server. Every unit test passed, because every unit
 * was fine.
 *
 * So the last suite here is not about a decision at all. It walks `app/` and asserts that
 * every route is reachable, and it is the one that would have failed. It stays useful as
 * the app grows: TASK-715 and TASK-716 each add a screen, and an unreferenced one fails
 * here rather than shipping as a file nobody can get to.
 */

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import type { Failure } from "@anuvritti/client";

import { noLongerPaired, noticingRevocation, whereToStart } from "../src/model/threshold.ts";

const APP = join(import.meta.dirname, "../app");
const SRC = join(import.meta.dirname, "../src");

describe("where a launch goes", () => {
  it("waits while the keychain is still being read", () => {
    // Not Today and not pairing. Both guesses are visible to a parent, and one of them
    // shows an empty archive to somebody who has years of one.
    assert.deepEqual(whereToStart("unknown"), { kind: "wait" });
  });

  it("sends a phone with no token to pairing", () => {
    assert.deepEqual(whereToStart("unpaired"), { kind: "pair" });
  });

  it("sends a phone with a token home", () => {
    assert.deepEqual(whereToStart("paired"), { kind: "home" });
  });
});

describe("a token that stopped working", () => {
  const api = (status: number): Failure => ({
    kind: "api",
    status,
    code: "UNAUTHORIZED",
    message: "no",
    details: {},
  });

  it("signs the device out on a 401", () => {
    // The checklist item this replaces: "revoke the second device from the first — the
    // second is signed out on its next call."
    assert.equal(noLongerPaired(api(401)), true);
  });

  it("does not sign the device out on a 403", () => {
    // A device that is in the family and was refused one particular thing. Signing it out
    // would turn "you may not revoke the owner" into "you are not in this family".
    assert.equal(noLongerPaired(api(403)), false);
  });

  it("does not sign the device out for being underground", () => {
    assert.equal(noLongerPaired({ kind: "offline", message: "no signal" }), false);
    assert.equal(noLongerPaired({ kind: "timeout", message: "slow" }), false);
  });

  it("notices a 401 at the transport and passes the response through untouched", async () => {
    let noticed = 0;
    const watched = noticingRevocation(
      async () => new Response("{}", { status: 401 }),
      () => (noticed += 1)
    );

    const response = await watched("https://home.example/v1/sparks");

    assert.equal(noticed, 1);
    assert.equal(response.status, 401, "the caller still sees its own failure");
  });

  it("says nothing about a call that worked", async () => {
    let noticed = 0;
    const watched = noticingRevocation(
      async () => new Response("{}", { status: 200 }),
      () => (noticed += 1)
    );
    await watched("https://home.example/v1/sparks");
    assert.equal(noticed, 0);
  });

  it("clears the token and never the queue", () => {
    // The worst bug this product could have: a parent captures five things on a plane,
    // lands, the token has been revoked, and the tidy-up takes the five with it.
    const provider = readFileSync(join(SRC, "provider.tsx"), "utf8");
    const revoked = provider.slice(provider.indexOf("const revoked ="));
    const body = revoked.slice(0, revoked.indexOf("\n  }, ["));

    assert.match(body, /forget\(\)/, "the token goes");
    assert.doesNotMatch(
      body,
      /queue|clear\(\)|drain\(\)/,
      "the queue is not the credential and must survive being signed out"
    );
  });
});

describe("every screen can be got to", () => {
  /** The routes expo-router will build from `app/`. `_layout` is not one of them. */
  function routes(): readonly string[] {
    return readdirSync(APP)
      .filter((name) => name.endsWith(".tsx") && !name.startsWith("_"))
      .map((name) => name.replace(/\.tsx$/, ""));
  }

  /** Every source file that could point at a route. */
  function everySource(): string {
    const read = (dir: string): string =>
      readdirSync(dir, { withFileTypes: true })
        .map((entry) =>
          entry.isDirectory()
            ? read(join(dir, entry.name))
            : /\.tsx?$/.test(entry.name)
              ? readFileSync(join(dir, entry.name), "utf8")
              : ""
        )
        .join("\n");
    return read(APP) + "\n" + read(SRC);
  }

  it("has a route for pairing, and something that points at it", () => {
    assert.ok(routes().includes("pair"), "app/pair.tsx is the route this all hangs on");
  });

  it("leaves no route orphaned", () => {
    const source = everySource();
    const orphans = routes().filter((route) => {
      // `index` is the anchor: it is where the router lands with no path at all.
      if (route === "index") return false;
      // A route is reachable if a link, a redirect, an imperative push, or a declared
      // screen names it. `Stack.Screen name="pair"` counts — declaring it inside a guard
      // is exactly how the router is told the screen exists.
      const named = new RegExp(
        String.raw`(href=["'{\s]*/${route}\b)` +
          String.raw`|(\b(push|replace|navigate)\(["'\`]/${route}\b)` +
          String.raw`|(name=["']${route}["'])`
      );
      return !named.test(source);
    });

    assert.deepEqual(
      orphans,
      [],
      `nothing points at ${orphans.join(", ")} — the screen exists and cannot be reached, ` +
        "which is how pairing shipped unreachable"
    );
  });

  it("guards the two groups against each other", () => {
    // Not a style check. Without the guards an unpaired phone still has Today to fall back
    // to, and falling back to Today is precisely the bug.
    const layout = readFileSync(join(APP, "_layout.tsx"), "utf8");
    const guards = [...layout.matchAll(/<Stack\.Protected guard=\{([^}]+)\}/g)].map((m) =>
      m[1]?.trim()
    );

    assert.deepEqual(guards, ['start.kind === "home"', 'start.kind === "pair"']);
  });

  it("loads every face it names, mono included", () => {
    // Mono is named by `world.font.mono` and used at size in exactly one place: the eight
    // characters of a pairing code. It was imported and never loaded, so it fell back to
    // the proportional system face — where `O`/`0` and `I`/`1` are the confusions the
    // Crockford alphabet exists to prevent.
    const layout = readFileSync(join(APP, "_layout.tsx"), "utf8");
    const loaded = layout.slice(layout.indexOf("useFonts({"), layout.indexOf("});"));
    const world = readFileSync(join(SRC, "world.ts"), "utf8");
    const named = [...world.matchAll(/^\s+\w+: "((?:Newsreader|IBMPlex)\w+)",$/gm)].map(
      (match) => match[1]
    );

    assert.ok(named.length >= 4, "the faces are named in world.ts");
    for (const face of new Set(named)) {
      assert.match(loaded, new RegExp(`\\b${face}\\b`), `${face} is named but never loaded`);
    }
  });
});
