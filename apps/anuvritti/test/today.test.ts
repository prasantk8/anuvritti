/**
 * TASK-807 — Papa Today (PRD 16, PRD 8.4, PRD 8.5).
 *
 * Tests verifying:
 * 1. At most one line a day.
 * 2. Silence (null) is a normal, valid output.
 * 3. Copy tells the parent to be present or record, with zero guilt and zero scorekeeping.
 * 4. Pronoun and name handling.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { Elapsed, Instant, Spark } from "@anuvritti/client";

import { papaToday } from "../src/model/today.ts";

function fakeSpark(id: string, title: string): Spark {
  return {
    id,
    family_id: "fam-001",
    owner_id: "mem-001",
    title,
    source: { kind: "TEXT", title },
    intent: { value: "DO", source: "HUMAN", confidence: 1.0, human_override: true },
    category: { value: "crafts", source: "DEFAULT", confidence: 0.0, human_override: false },
    tags: [],
    status: "WAITING",
    visibility: "FAMILY",
    saved: "a while ago" as Elapsed,
    created_at: "2024-01-01T00:00:00Z" as Instant,
  };
}

describe("TASK-807 — Papa Today", () => {
  it("generates ambient gentle prompts for presence and voice", () => {
    const thoughtHe = papaToday({ dayOrdinal: 0, childName: "Leo", childPronoun: "he" });
    assert.equal(thoughtHe?.text, "Leave him a twenty-second message.");
    assert.equal(thoughtHe?.kind, "voice");

    const thoughtShe = papaToday({ dayOrdinal: 1, childName: "Maya", childPronoun: "she" });
    assert.equal(thoughtShe?.text, "Put the phone down and go sit with her.");
    assert.equal(thoughtShe?.kind, "close_app");
  });

  it("returns silence (null) on designated quiet intervals", () => {
    // Large ordinal that lands on silence slot
    const silence = papaToday({ dayOrdinal: 7, childName: "Leo" });
    assert.equal(silence, null);
  });

  it("recalls an old spark from the archive warmly", () => {
    const sparks = [fakeSpark("spk-moon", "The Moon")];
    const thought = papaToday({
      dayOrdinal: 0,
      recentSparks: sparks,
      childName: "Leo",
    });

    assert.ok(thought);
    assert.match(thought.text, /saved something about the moon/i);
    assert.equal(thought.kind, "spark_recall");
    assert.equal(thought.sparkId, "spk-moon");
  });

  it("never contains guilt, urgency, streaks, or exclamation marks across 100 days", () => {
    for (let day = 0; day < 100; day++) {
      const thought = papaToday({
        dayOrdinal: day,
        childName: "Aarav",
        childPronoun: "he",
        recentSparks: [fakeSpark("spk-stars", "Stargazing")],
      });

      if (thought) {
        assert.doesNotMatch(thought.text, /!/);
        assert.doesNotMatch(
          thought.text,
          /streak|score|rank|overdue|missed|forgot|behind|hurry|days ago/i
        );
      }
    }
  });
});
