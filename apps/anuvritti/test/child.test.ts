/**
 * TASK-818 — Child View Tests (PRD 19, PRD 63.6).
 *
 * Stillness verification:
 * - Plays one chosen item.
 * - Transitions to dark, still state on playback finish.
 * - Emits zero events once dark.
 * - Refuses access without parent PIN.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  BEDTIME_GOODNIGHT_TEXT,
  type ChildBedtimeMedia,
  type ChildViewState,
  isScreenStill,
  transitionOnPlaybackEnd,
  verifyParentPin,
} from "../src/model/child.ts";

describe("TASK-818 — Child View Bedtime Stillness", () => {
  const sampleMedia: ChildBedtimeMedia = {
    id: "bed-1",
    title: "Bedtime Story with Dadi",
    type: "voice_note",
    mediaId: "med-story-1",
    authorName: "Dadi",
  };

  it("initializes in ready state with selected media", () => {
    const state: ChildViewState = { kind: "ready", media: sampleMedia };
    assert.equal(state.kind, "ready");
    assert.equal(state.media.title, "Bedtime Story with Dadi");
    assert.equal(isScreenStill(state), false);
  });

  it("transitions immediately to dark finished state on playback end", () => {
    const playing: ChildViewState = { kind: "playing", media: sampleMedia };
    const finished = transitionOnPlaybackEnd(playing);
    assert.equal(finished.kind, "finished_dark");
    assert.equal(isScreenStill(finished), true);
  });

  it("contains calm goodnight copy without urgency or streaks", () => {
    assert.match(BEDTIME_GOODNIGHT_TEXT, /goodnight/i);
    assert.doesNotMatch(BEDTIME_GOODNIGHT_TEXT, /streak|badge|point|next up/i);
  });

  it("verifies parent PIN to leave child mode", () => {
    assert.equal(verifyParentPin("1234", "1234"), true);
    assert.equal(verifyParentPin("0000", "1234"), false);
    assert.equal(verifyParentPin("", "1234"), false);
  });
});
