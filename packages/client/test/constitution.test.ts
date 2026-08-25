/**
 * TASK-507 and TASK-510, held by the client itself.
 *
 * The server's half is that it never sends the number. This is the other half: this package
 * cannot compute one. Not "does not" — the test reads its own source and fails if any date
 * arithmetic appears in it, so a future change under a deadline hits a red test rather than
 * a code review that might be skipped.
 *
 * A rule that only exists in the server is one deploy away from being worked around.
 */

import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import type { IntentType, Spark } from "../src/index.ts";
import {
  INTENT_SAID,
  INTENT_TYPE_VALUES,
  NEXT_INTENT,
  ageRangeOf,
  asElapsed,
  compareInstants,
  correctIntent,
  intentCycle,
  intentOf,
  isUncertain,
  nearness,
  newestFirst,
  savedSentence,
} from "../src/index.ts";
import { aSpark, serverDouble } from "./support.ts";

const SRC = new URL("../src", import.meta.url).pathname;

function sourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return path.endsWith(".ts") ? [path] : [];
  });
}

/** Source with comments stripped: a comment naming a construct is not using it. */
function code(path: string): string {
  return readFileSync(path, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

describe("this package cannot compute an elapsed time", () => {
  const forbidden: [string, RegExp][] = [
    ["new Date(...)", /\bnew Date\s*\(/],
    ["Date.parse", /\bDate\.parse\s*\(/],
    ["Date.now", /\bDate\.now\s*\(/],
    ["getTime()", /\.getTime\s*\(/],
    ["valueOf() on a date", /\.valueOf\s*\(\s*\)/],
  ];

  for (const [name, pattern] of forbidden) {
    it(`contains no ${name}`, () => {
      const offenders = sourceFiles(SRC).filter((path) => pattern.test(code(path)));
      assert.deepEqual(
        offenders.map((path) => path.replace(SRC, "src")),
        [],
        `${name} is how "8 months ago" becomes "247 days" the week before a release`
      );
    });
  }

  it("would catch the line it exists to forbid", () => {
    // Five tests that scan for a pattern will all pass against a pattern that matches
    // nothing. This is the mutation: the exact line someone would write under a deadline,
    // fed to the same regexes, with every one of them required to fire.
    const mutations: Record<string, string> = {
      "new Date(...)": "const then = new Date(spark.created_at);",
      "Date.parse": "const ms = Date.parse(spark.created_at);",
      "Date.now": "const days = (Date.now() - saved) / 86400000;",
      "getTime()": "const ms = someDate.getTime();",
      "valueOf() on a date": "const ms = someDate.valueOf();",
    };

    for (const [name, pattern] of forbidden) {
      const mutation = mutations[name];
      assert.ok(mutation, `no mutation written for ${name}`);
      assert.ok(pattern.test(mutation), `the guard for ${name} does not match ${mutation}`);
    }
  });

  it("orders instants without producing a duration", () => {
    const older = "2026-01-13T21:40:00+00:00" as never;
    const newer = "2026-09-13T10:00:00+00:00" as never;

    assert.equal(compareInstants(older, newer), -1);
    assert.equal(compareInstants(newer, older), 1);
    assert.equal(compareInstants(older, older), 0);
  });

  it("sorts a vault newest first", () => {
    const old = aSpark({ id: "old", created_at: "2026-01-13T21:40:00+00:00" }) as unknown as Spark;
    const recent = aSpark({
      id: "recent",
      created_at: "2026-09-13T10:00:00+00:00",
    }) as unknown as Spark;

    assert.deepEqual(
      newestFirst([old, recent]).map((spark) => spark.id),
      ["recent", "old"]
    );
  });

  it("says the phrase the server sent, and never assembles one", () => {
    assert.equal(savedSentence(asElapsed("8 months ago")), "You saved this 8 months ago.");
    assert.equal(savedSentence(asElapsed("today")), "You saved this today.");
  });

  it("knows only three degrees of how long ago, which is the ceiling on purpose", () => {
    assert.equal(nearness(asElapsed("today")), "today");
    assert.equal(nearness(asElapsed("yesterday")), "today");
    assert.equal(nearness(asElapsed("3 days ago")), "recent");
    assert.equal(nearness(asElapsed("2 weeks ago")), "recent");
    assert.equal(nearness(asElapsed("8 months ago")), "a while ago");
    assert.equal(nearness(asElapsed("2 years ago")), "a while ago");
  });
});

describe("a machine's guess never looks like a fact", () => {
  it("carries confidence through, so low confidence can be phrased as a question", () => {
    const spark = aSpark({
      intent: { value: "DO", source: "AI", confidence: 0.3, human_override: false },
    }) as unknown as Spark;

    assert.equal(isUncertain(spark.intent), true);
    assert.equal(intentOf(spark)?.confidence, 0.3);
  });

  it("does not call a human's own statement uncertain", () => {
    const spark = aSpark({
      intent: { value: "DO", source: "HUMAN", confidence: 1, human_override: true },
    }) as unknown as Spark;
    assert.equal(isUncertain(spark.intent), false);
  });

  it("returns null rather than guessing when the wire held something unexpected", () => {
    const spark = aSpark({
      intent: { value: "TELEPORT", source: "AI", confidence: 0.9, human_override: false },
    }) as unknown as Spark;

    assert.equal(intentOf(spark), null, "a cast would put an impossible intent into the UI");
  });

  it("reads an age range only when it is actually one", () => {
    assert.deepEqual(ageRangeOf(aSpark() as unknown as Spark)?.value, {
      min_years: 5,
      max_years: 8,
    });
    assert.equal(ageRangeOf(aSpark({ age_range: null }) as unknown as Spark), null);
    assert.equal(
      ageRangeOf(
        aSpark({
          age_range: { value: "five to eight", source: "AI", confidence: 1, human_override: false },
        }) as unknown as Spark
      ),
      null
    );
  });
});

describe("correction is one tap and never a form", () => {
  it("every intent can reach every other, and comes back to itself", () => {
    for (const start of INTENT_TYPE_VALUES) {
      const cycle = intentCycle(start);
      assert.equal(cycle.length, INTENT_TYPE_VALUES.length, `${start} cannot reach them all`);
      assert.equal(new Set(cycle).size, cycle.length, `${start} repeats before it finishes`);
      assert.equal(cycle[0], start);
    }
  });

  it("no intent is a dead end", () => {
    for (const intent of INTENT_TYPE_VALUES) {
      const alternatives = NEXT_INTENT[intent];
      assert.equal(
        new Set([intent, ...alternatives]).size,
        INTENT_TYPE_VALUES.length,
        `${intent} does not list every alternative, so some are unreachable`
      );
      assert.ok(!alternatives.includes(intent), `${intent} lists itself as an alternative`);
    }
  });

  it("every intent has words a parent would use", () => {
    for (const intent of INTENT_TYPE_VALUES) {
      const said = INTENT_SAID[intent as IntentType];
      assert.ok(said && said === said.toLowerCase(), `${intent} has no lowercase phrasing`);
      assert.ok(!said.includes("_"), `${intent} is phrased as an identifier, not as speech`);
    }
  });

  it("changes the chip before the network answers", async () => {
    const server = serverDouble();
    server.on("POST /sparks/sp-1/override", { hang: true });

    const { createClient, memoryTokenStore } = await import("../src/index.ts");
    const { api } = createClient({
      baseUrl: "https://anuvritti.local",
      tokens: memoryTokenStore("anv_token"),
      fetch: server.fetch,
      timeoutMs: 20,
    });

    const correction = correctIntent(api, aSpark() as unknown as Spark);
    assert.equal(correction?.optimistic, "WATCH", "DO's likeliest correction is WATCH");

    // A parent who has to wait for a server before the word changes taps twice, and the
    // second tap corrects the correction.
    await correction?.confirmed;
  });

  it("sends the override rather than a whole edited Spark", async () => {
    const server = serverDouble();
    server.on("POST /sparks/sp-1/override", { json: aSpark({ intent: { value: "WATCH", source: "HUMAN", confidence: 1, human_override: true } }) });

    const { createClient, memoryTokenStore } = await import("../src/index.ts");
    const { api } = createClient({
      baseUrl: "https://anuvritti.local",
      tokens: memoryTokenStore("anv_token"),
      fetch: server.fetch,
    });

    await correctIntent(api, aSpark() as unknown as Spark)?.confirmed;
    assert.deepEqual(server.lastCall()?.body, { field: "intent", value: "WATCH" });
  });
});
