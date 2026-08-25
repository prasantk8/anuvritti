/**
 * TASK-605 — Little Things, and the seed of the Papa Voice Vault.
 *
 * The vault is where the constitution is under the most pressure, because a list of
 * recordings is begging for a number at the top of it. So most of this file is about what
 * the shelf cannot say, checked at the level of the shape rather than the copy.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import type { VoiceNote } from "@anuvritti/client";

import {
  KEPT,
  NOTHING_YET,
  WORTH_SAYING,
  shelve,
  worthSayingOn,
} from "../src/model/vault.ts";

/** Source with comments removed, so prose about a rule never trips the rule. */
function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

function recorded(on: string, id = on): VoiceNote {
  return {
    media_id: id,
    duration_seconds: 4.2,
    recorded_at: `${on}T21:40:00+00:00` as VoiceNote["recorded_at"],
  };
}

describe("the shelf", () => {
  it("groups by month, newest first, the way the server sent them", () => {
    const shelf = shelve([
      recorded("2026-08-25"),
      recorded("2026-08-02"),
      recorded("2026-07-30"),
    ]);
    assert.deepEqual(
      shelf.map((period) => period.named),
      ["August 2026", "July 2026"]
    );
    assert.equal(shelf[0]?.recordings.length, 2);
  });

  it("does not re-sort, because the ordering is the server's answer", () => {
    // The same rule `whatToBringBack` holds: a second opinion here would only ever be a bug.
    const shelf = shelve([recorded("2026-07-30"), recorded("2026-08-25")]);
    assert.deepEqual(
      shelf.map((period) => period.named),
      ["July 2026", "August 2026"]
    );
  });

  it("keeps a month that comes back around as its own run rather than merging it", () => {
    const shelf = shelve([recorded("2026-08-25"), recorded("2025-08-02")]);
    assert.deepEqual(
      shelf.map((period) => period.named),
      ["August 2026", "August 2025"]
    );
  });

  it("carries no count of any kind", () => {
    const shelf = shelve([recorded("2026-08-25"), recorded("2026-08-02")]);
    for (const period of shelf) {
      assert.deepEqual(Object.keys(period).sort(), ["named", "recordings"]);
    }
  });

  it("cannot describe how far behind anyone is", () => {
    // A badge needs an unread state, a total, or a since-you-last-looked. None of the three
    // exists on this type, so building one means editing vault.ts.
    const source = readFileSync(new URL("../src/model/vault.ts", import.meta.url), "utf8");
    for (const forbidden of ["unread", "unheard", "total", "count", "since", "streak"]) {
      assert.ok(
        !new RegExp(`readonly ${forbidden}`, "i").test(source),
        `the vault can express "${forbidden}"`
      );
    }
  });

  it("is empty rather than broken when nothing has been recorded", () => {
    assert.deepEqual(shelve([]), []);
  });

  it("reads a month off the timestamp without ever parsing it into a Date", () => {
    // TASK-507's rule, held here for the same reason: once a timestamp is a `Date`,
    // subtracting two of them is one keystroke away.
    //
    // Comments are stripped first. The rule is about what the code does, and a file that
    // explains why it avoids `Date.parse` must not fail for having said the words.
    const source = withoutComments(
      readFileSync(new URL("../src/model/vault.ts", import.meta.url), "utf8")
    );
    for (const forbidden of ["new Date", "Date.parse", "Date.now", "getTime()", "valueOf()"]) {
      assert.ok(!source.includes(forbidden), `vault.ts uses ${forbidden}`);
    }
  });

  it("would notice if the code did start parsing dates", () => {
    // Proving the scan above is not passing because it stripped everything.
    const stripped = withoutComments('// Date.parse is bad\nconst a = Date.parse(x);\n');
    assert.ok(!stripped.includes("// Date.parse is bad"));
    assert.ok(stripped.includes("Date.parse(x)"));
  });
});

describe("the reason to record", () => {
  it("says what happens to a clip, in the present tense", () => {
    assert.equal(KEPT, "That's in this year's film.");
  });

  it("is a statement rather than a promise or a target", () => {
    assert.ok(!/will|soon|towards|progress|need|more/i.test(KEPT));
  });

  it("says nothing that could be a progress bar", () => {
    assert.ok(!/\d/.test(KEPT), "the acknowledgement contains a number");
    assert.ok(!/\d/.test(NOTHING_YET));
  });

  it("does not apologise for an empty shelf or ask anyone to fill it", () => {
    assert.ok(!/sorry|start|first|add|record your/i.test(NOTHING_YET));
    assert.match(NOTHING_YET, /voice lives/);
  });
});

describe("what is worth saying", () => {
  it("is always a noticing and never an assessment", () => {
    for (const prompt of WORTH_SAYING) {
      assert.match(prompt, /\?$/, `${prompt} is not a question`);
      assert.ok(
        !/how (well|often)|rate|score|progress|should you|are you/i.test(prompt),
        `${prompt} asks a parent to assess something`
      );
    }
  });

  it("never asks anyone to sound wise", () => {
    // PRD §17 names this failure directly: "No need to sound wise."
    for (const prompt of WORTH_SAYING) {
      assert.ok(!/wisdom|advice|lesson|profound|meaningful/i.test(prompt), prompt);
    }
  });

  it("gives the same question all day and a new one tomorrow", () => {
    assert.equal(worthSayingOn("2026-08-25"), worthSayingOn("2026-08-25"));
    assert.notEqual(worthSayingOn("2026-08-25"), worthSayingOn("2026-08-26"));
  });

  it("gets through the whole set rather than favouring a few", () => {
    const seen = new Set<string>();
    for (let day = 1; day <= 28; day += 1) {
      seen.add(worthSayingOn(`2026-09-${String(day).padStart(2, "0")}`));
    }
    assert.equal(seen.size, WORTH_SAYING.length);
  });

  it("still has something to say when handed something that is not a date", () => {
    assert.equal(worthSayingOn(""), WORTH_SAYING[0]);
    assert.equal(worthSayingOn("not-a-date"), WORTH_SAYING[0]);
  });
});

describe("nothing here nags", () => {
  it("carries no guilt or urgency anywhere in this module", () => {
    // The same boundary tests/constitution/test_no_guilt.py holds on the server.
    const source = readFileSync(new URL("../src/model/vault.ts", import.meta.url), "utf8");
    const strings = [...source.matchAll(/"([^"\\]{4,})"/g)].map((match) => match[1]!);
    const forbidden =
      /\b(overdue|behind|missed|forgot to|streak|don't forget|reminder|still haven't|you should|keep it up)\b/i;

    for (const said of strings) {
      assert.ok(!forbidden.test(said), `this is said to a parent about their child: ${said}`);
    }
    assert.ok(strings.length > 5, "the scan found almost no strings, so it proves nothing");
  });

  it("would catch a nagging string if one were added", () => {
    const forbidden = /\b(overdue|behind|missed|streak|you should|keep it up)\b/i;
    assert.ok(forbidden.test("You're 3 behind this month"));
    assert.ok(forbidden.test("Keep it up!"));
    assert.ok(!forbidden.test("That's in this year's film."));
  });
});
