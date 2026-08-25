/**
 * TASK-602 — the recording renders above the text, and the text never replaces it.
 *
 * These are type-level and shape-level assertions rather than pixel ones. The rule this
 * feature exists to hold cannot be checked by looking at a screen once; it has to be held
 * by a shape that has no way to express the wrong answer.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import type { Transcript, VoiceNote } from "@anuvritti/client";

import { UNSURE, describe as describeAloud, lengthOf, whatToShow, whyFrom } from "../src/voice/playback.ts";

function note(transcript?: Partial<Transcript>): VoiceNote {
  return {
    media_id: "med-1",
    duration_seconds: 4.2,
    recorded_at: "2026-01-13T21:40:00+00:00" as VoiceNote["recorded_at"],
    transcript: transcript
      ? ({
          text: "he called the elevator an alligator",
          source: "AI",
          confidence: 0.72,
          engine: "device-speech",
          made_at: "2026-01-13T21:40:00+00:00",
          ...transcript,
        } as Transcript)
      : undefined,
  };
}

describe("the player is not optional", () => {
  it("is present for a recording nobody has transcribed", () => {
    const shown = whatToShow(note());
    assert.deepEqual(shown.player, { mediaId: "med-1", seconds: 4.2 });
    assert.equal(shown.words, null);
  });

  it("is present for one that has been transcribed", () => {
    const shown = whatToShow(note({}));
    assert.deepEqual(shown.player, { mediaId: "med-1", seconds: 4.2 });
    assert.ok(shown.words);
  });

  it("has no shape that renders words without it", () => {
    // The rule as a type rather than a habit. `player` is non-nullable and `words` is not,
    // so building the wrong screen means editing playback.ts — which is the point.
    const source = readFileSync(new URL("../src/voice/playback.ts", import.meta.url), "utf8");
    assert.match(source, /readonly player: Player;/);
    assert.match(source, /readonly words: Words \| null;/);
  });

  it("treats an empty transcript as no transcript rather than as empty words", () => {
    assert.equal(whatToShow(note({ text: "   " })).words, null);
  });
});

describe("the words say who said them", () => {
  it("hedges a confident machine reading and still hedges it", () => {
    const words = whatToShow(note({ confidence: 0.8 })).words;
    assert.equal(words?.kind, "heard");
    assert.equal(words?.kind === "heard" && words.said, "It sounded like");
  });

  it("hedges an unsure one harder", () => {
    const words = whatToShow(note({ confidence: 0.3 })).words;
    assert.equal(words?.kind === "heard" && words.said, "Maybe");
    assert.equal(words?.kind === "heard" && words.sure, false);
  });

  it("draws the line exactly where the domain draws it", () => {
    // `Confidence.is_low` on the server is `< 0.5`. The same boundary, so a reading is
    // never hedged on one side of the wire and quoted on the other.
    const atTheLine = whatToShow(note({ confidence: UNSURE })).words;
    const justUnder = whatToShow(note({ confidence: UNSURE - 0.01 })).words;
    assert.equal(atTheLine?.kind === "heard" && atTheLine.sure, true);
    assert.equal(justUnder?.kind === "heard" && justUnder.sure, false);
  });

  it("presents what a parent typed plainly, because it is not a guess", () => {
    const words = whatToShow(note({ source: "HUMAN", confidence: 1 })).words;
    assert.equal(words?.kind, "written");
    assert.ok(!("said" in (words ?? {})));
  });

  it("never presents a machine reading as a quotation", () => {
    for (const confidence of [0.1, 0.4, 0.5, 0.84]) {
      const words = whatToShow(note({ confidence })).words;
      assert.equal(words?.kind, "heard");
    }
  });
});

describe("how long it is", () => {
  it("rounds up, because a half-second clip is not nothing", () => {
    assert.equal(lengthOf(0.4), "1 sec");
    assert.equal(lengthOf(0), "1 sec");
    assert.equal(lengthOf(4.2), "5 sec");
  });

  it("says minutes once there are any", () => {
    assert.equal(lengthOf(60), "1 min");
    assert.equal(lengthOf(95), "1 min 35 sec");
  });
});

describe("what a screen reader is told", () => {
  it("reads the words out, because they are the only way to know before playing", () => {
    const said = describeAloud(whatToShow(note({})));
    assert.match(said, /Recording, 5 sec\./);
    assert.match(said, /It sounded like: he called the elevator an alligator/);
  });

  it("reads the hedge out too", () => {
    assert.match(describeAloud(whatToShow(note({ confidence: 0.2 }))), /Maybe:/);
  });

  it("says what it is when there is nothing to read", () => {
    assert.equal(describeAloud(whatToShow(note())), "Recording, 5 sec.");
  });

  it("does not hedge a person's own words", () => {
    const said = describeAloud(whatToShow(note({ source: "HUMAN", confidence: 1 })));
    assert.ok(!/sounded like|Maybe/.test(said));
  });
});

describe("a why that has both", () => {
  it("leads with the recording and keeps the text under it", () => {
    const why = whyFrom({ text: "I never had one growing up", voice: note({}) });
    assert.ok(why.voice);
    assert.equal(why.text, "I never had one growing up");
  });

  it("is words alone when that is all there is", () => {
    const why = whyFrom({ text: "he would love it", voice: null });
    assert.equal(why.voice, null);
    assert.equal(why.text, "he would love it");
  });

  it("is a recording alone when that is all there is", () => {
    const why = whyFrom({ text: null, voice: note() });
    assert.ok(why.voice);
    assert.equal(why.text, null);
  });

  it("does not turn whitespace into a second answer", () => {
    assert.equal(whyFrom({ text: "  ", voice: note() }).text, null);
  });
});
