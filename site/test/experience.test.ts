import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createSparkExperience, createVoiceExperience } from "../experience/index.ts";

describe("embedded product experience on website", () => {
  it("flips spark card cleanly between front and why statements", () => {
    const exp = createSparkExperience({
      id: "spark-demo-1",
      title: "Building rocket ship from cardboard",
      whyText: "He spent 3 hours decorating it with silver foil",
    });

    assert.equal(exp.state.isFlipped, false);
    exp.flip();
    assert.equal(exp.state.isFlipped, true);
    exp.flip();
    assert.equal(exp.state.isFlipped, false);
  });

  it("handles hold-to-talk recording state and samples meter levels", () => {
    const voice = createVoiceExperience();
    assert.equal(voice.getState().isRecording, false);

    voice.start();
    assert.equal(voice.getState().isRecording, true);

    voice.sample(0.4);
    voice.sample(0.8);
    voice.sample(0.2);

    const activeState = voice.getState();
    assert.equal(activeState.meterLevels.length, 3);
    assert.equal(activeState.durationMs, 300);

    voice.stop();
    assert.equal(voice.getState().isRecording, false);
  });
});
