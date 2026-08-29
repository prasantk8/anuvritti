/**
 * TASK-512 — Worth Bringing Back, on a phone.
 *
 * These are constitution tests wearing a product hat. Every one of them fails if the screen
 * starts behaving like an inbox.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import type { Suggestion } from "@anuvritti/client";

import { ACKNOWLEDGEMENT, ANSWERS, NOTHING_TODAY, whatToBringBack } from "../src/model/worth.ts";

function suggestion(id: string): Suggestion {
  return {
    spark: { id } as Suggestion["spark"],
    reason: `You saved this 8 months ago.`,
    elapsed: "8 months ago" as Suggestion["elapsed"],
    actions: ["maybe_later", "lets_do_it", "not_relevant_anymore"],
  };
}

describe("at most one", () => {
  it("shows one when the server offered three", () => {
    const chosen = whatToBringBack([suggestion("a"), suggestion("b"), suggestion("c")]);

    assert.equal(chosen.kind, "one");
    // Three is a list, a list is a queue, and a queue is something to be behind on.
    assert.equal(chosen.kind === "one" && chosen.suggestion.spark.id, "a");
  });

  it("takes the server's order rather than re-ranking", () => {
    const chosen = whatToBringBack([suggestion("second-best"), suggestion("best")]);
    assert.equal(chosen.kind === "one" && chosen.suggestion.spark.id, "second-best");
  });

  it("shows nothing when there is nothing, and that is a finished state", () => {
    assert.deepEqual(whatToBringBack([]), { kind: "nothing" });
  });

  it("moves on to the next once one is dismissed", () => {
    const chosen = whatToBringBack([suggestion("a"), suggestion("b")], new Set(["a"]));
    assert.equal(chosen.kind === "one" && chosen.suggestion.spark.id, "b");
  });

  it("shows nothing once they are all dismissed, rather than repeating the first", () => {
    const chosen = whatToBringBack([suggestion("a"), suggestion("b")], new Set(["a", "b"]));
    assert.equal(chosen.kind, "nothing");
  });

  it("cannot express how many there were", () => {
    // The type has no count and no "more" - so a badge cannot be built from it without
    // changing this file, which is the point.
    const chosen = whatToBringBack([suggestion("a"), suggestion("b"), suggestion("c")]);
    assert.deepEqual(Object.keys(chosen).sort(), ["kind", "suggestion"]);
  });
});

describe("the three answers", () => {
  it("are exactly the three the PRD names, and there is no fourth", () => {
    assert.deepEqual(
      ANSWERS.map((answer) => answer.action),
      ["maybe_later", "lets_do_it", "not_relevant_anymore"]
    );
  });

  it("do not put the affirmative first", () => {
    // Leading with "Let's do it" makes the other two read as refusals of an invitation.
    assert.notEqual(ANSWERS[0]?.action, "lets_do_it");
    assert.equal(ANSWERS[1]?.action, "lets_do_it");
  });

  it("are each acknowledged as a statement rather than a confirmation", () => {
    for (const answer of ANSWERS) {
      const said = ACKNOWLEDGEMENT[answer.action];
      assert.ok(said, `${answer.action} says nothing back`);
      assert.ok(!said.includes("?"), `${answer.action} asks a question back`);
      assert.ok(!/undo/i.test(said), `${answer.action} offers to take it back`);
    }
  });

  it('promises real quiet for "maybe later" rather than a snooze', () => {
    assert.match(ACKNOWLEDGEMENT.maybe_later, /while/);
  });

  it('says out loud that "not anymore" is permanent', () => {
    // A parent who does not believe it is permanent will not use it.
    assert.match(ACKNOWLEDGEMENT.not_relevant_anymore, /won't come back/i);
  });
});

describe("the words on the screen", () => {
  it("does not apologise for having nothing", () => {
    assert.match(NOTHING_TODAY, /normal/);
    assert.ok(!/sorry|check back|come back|later/i.test(NOTHING_TODAY));
  });

  it("carries no guilt or urgency anywhere in this module", () => {
    // The same boundary tests/constitution/test_no_guilt.py holds on the server, held here
    // on the strings the phone actually renders.
    const source = readFileSync(join(import.meta.dirname, "../src/model/worth.ts"), "utf8");
    const strings = [...source.matchAll(/"([^"\\]{4,})"/g)].map((match) => match[1]!);
    const forbidden =
      /\b(overdue|behind|missed|forgot to|streak|don't forget|reminder|still haven't|you should)\b/i;

    for (const said of strings) {
      assert.ok(!forbidden.test(said), `this is said to a parent about their child: ${said}`);
    }
  });

  it("would catch a guilty string if one were added", () => {
    // Proving the scan above is not vacuous.
    const forbidden =
      /\b(overdue|behind|missed|forgot to|streak|don't forget|reminder|still haven't|you should)\b/i;
    assert.ok(forbidden.test("You still haven't done this."));
    assert.ok(forbidden.test("3 overdue"));
    assert.ok(!forbidden.test("Nothing today. That's normal."));
  });
});
