/**
 * TASK-601 — hold to talk, and the live waveform.
 *
 * The state machine and the waveform are the two parts of this feature that can be wrong
 * without looking wrong, so they are the two parts that are pure and tested. What is left
 * for `docs/DEVICE.md` is whether it *feels* like holding a button and speaking, which no
 * assertion can answer.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  ARMING_MS,
  RESTING,
  type Recording,
  type Signal,
  announce,
  elapsed,
  isLive,
  step,
} from "../src/voice/recording.ts";
import {
  FLOOR_DB,
  FLOOR_HEIGHT,
  WINDOW,
  clock,
  heightOf,
  push,
  resting,
  summarise,
} from "../src/voice/waveform.ts";

/** Run a gesture and hand back the last state plus every effect it asked for. */
function gesture(...signals: readonly Signal[]): {
  state: Recording;
  effects: readonly string[];
} {
  let state = RESTING;
  const effects: string[] = [];
  for (const signal of signals) {
    const next = step(state, signal);
    state = next.state;
    if (next.effect !== "none") effects.push(next.effect);
  }
  return { state, effects };
}

describe("a tap is not a recording", () => {
  it("does not start audio on the press itself", () => {
    const { state, effects } = gesture({ kind: "press", at: 0 });
    assert.equal(state.phase, "arming");
    assert.deepEqual(effects, []);
  });

  it("goes back to rest when released before it was meant", () => {
    const { state, effects } = gesture(
      { kind: "press", at: 0 },
      { kind: "tick", at: 80 },
      { kind: "release", at: 120 }
    );
    assert.deepEqual(state, RESTING);
    // Nothing to keep, because nothing was ever captured. That is the entire justification
    // for the arming state existing at all.
    assert.deepEqual(effects, []);
  });

  it("starts audio once the press has been held long enough", () => {
    const { state, effects } = gesture({ kind: "press", at: 0 }, { kind: "tick", at: ARMING_MS });
    assert.equal(state.phase, "recording");
    assert.deepEqual(effects, ["start"]);
  });

  it("filters the gesture and never the recording", () => {
    // The distinction the constitution test is built around, asserted directly: no signal
    // sequence produces an effect that throws audio away.
    const { effects } = gesture(
      { kind: "press", at: 0 },
      { kind: "tick", at: 250 },
      { kind: "release", at: 300 }
    );
    assert.ok(!effects.includes("discard" as never));
    assert.deepEqual(effects, ["start", "stop"]);
  });
});

describe("release always keeps what was captured", () => {
  it("keeps a recording of a fifth of a second", () => {
    const { state } = gesture(
      { kind: "press", at: 0 },
      { kind: "tick", at: 200 },
      { kind: "release", at: 400 }
    );
    assert.equal(state.phase, "keeping");
    assert.equal(state.seconds, 0.2);
  });

  it("keeps a five second one the same way, with no branch between them", () => {
    const { state } = gesture(
      { kind: "press", at: 0 },
      { kind: "tick", at: 200 },
      { kind: "release", at: 5200 }
    );
    assert.equal(state.phase, "keeping");
    assert.equal(state.seconds, 5);
  });

  it("keeps what was said when a phone call takes the microphone", () => {
    // Treating an interruption as an abandonment loses four seconds of a parent's voice to
    // an incoming spam call, and there is no way to ask for them back.
    const { state, effects } = gesture(
      { kind: "press", at: 0 },
      { kind: "tick", at: 200 },
      { kind: "interrupted", at: 4400 }
    );
    assert.equal(state.phase, "keeping");
    assert.equal(state.seconds, 4.2);
    assert.deepEqual(effects, ["start", "keep"]);
  });

  it("returns to rest only once the keep has settled", () => {
    const held = gesture(
      { kind: "press", at: 0 },
      { kind: "tick", at: 200 },
      { kind: "release", at: 1200 }
    ).state;
    assert.equal(step(held, { kind: "press", at: 1300 }).state.phase, "keeping");
    assert.deepEqual(step(held, { kind: "settled" }).state, RESTING);
  });

  it("clamps a stale timestamp to zero rather than to a negative length", () => {
    const { state } = gesture(
      { kind: "press", at: 1000 },
      { kind: "tick", at: 1200 },
      { kind: "release", at: 900 }
    );
    // Zero is kept by the server. Negative is refused by it, and correctly.
    assert.equal(state.seconds, 0);
  });
});

describe("what the interface can say about it", () => {
  it("is never vague about whether the microphone is live", () => {
    const armed = gesture({ kind: "press", at: 0 }).state;
    const live = gesture({ kind: "press", at: 0 }, { kind: "tick", at: 200 }).state;
    assert.equal(isLive(armed), false);
    assert.equal(isLive(live), true);
  });

  it("reports no elapsed time before there is any", () => {
    assert.equal(elapsed(RESTING, 5000), 0);
    assert.equal(elapsed(gesture({ kind: "press", at: 0 }).state, 100), 0);
  });

  it("counts up from the moment audio started, not from the press", () => {
    const live = gesture({ kind: "press", at: 0 }, { kind: "tick", at: 200 }).state;
    assert.equal(elapsed(live, 3200), 3);
  });

  it("announces the two facts a screen reader has an absolute right to", () => {
    assert.equal(announce("recording"), "Recording.");
    assert.equal(announce("keeping"), "Saved.");
    assert.equal(announce("resting"), "Hold to talk.");
  });

  it("never asks a parent to speak up, hold longer or try again", () => {
    for (const phase of ["resting", "arming", "recording", "keeping"] as const) {
      assert.ok(!/again|longer|louder|short/i.test(announce(phase)), announce(phase));
    }
  });
});

describe("the waveform", () => {
  it("draws quiet as small, and never as nothing", () => {
    // A flat zero line reads as "it stopped recording", and a parent pausing to think
    // would then start over or stop to check.
    assert.equal(heightOf(FLOOR_DB), FLOOR_HEIGHT);
    assert.equal(heightOf(-160), FLOOR_HEIGHT);
    assert.ok(heightOf(-59) > FLOOR_HEIGHT);
  });

  it("gives a normal speaking voice most of the height", () => {
    // dBFS is logarithmic and so is hearing. Mapping the full [-160, 0] would leave a
    // conversational -20dB at an eighth of the bar.
    assert.ok(heightOf(-20) > 0.6);
    assert.equal(heightOf(0), 1);
  });

  it("draws at the floor rather than vanishing when there is no meter at all", () => {
    // `metering` is undefined until the first poll lands, and on platforms without it.
    // A missing meter is not a missing microphone.
    assert.equal(heightOf(undefined), FLOOR_HEIGHT);
    assert.equal(heightOf(Number.NaN), FLOOR_HEIGHT);
  });

  it("starts full so the shape never grows in from the left", () => {
    const start = resting(8);
    assert.equal(start.length, 8);
    assert.deepEqual([...new Set(start)], [FLOOR_HEIGHT]);
  });

  it("scrolls rather than growing once the window is full", () => {
    let bars = resting(3);
    bars = push(bars, -20, 3);
    bars = push(bars, 0, 3);
    assert.equal(bars.length, 3);
    assert.equal(bars[2], 1);
  });

  it("returns a new array so React actually re-renders", () => {
    const before = resting(4);
    assert.notEqual(push(before, -20, 4), before);
    assert.deepEqual(before, resting(4));
  });

  it("defaults to a window worth about four seconds of polling", () => {
    assert.equal(push([], -20).length, 1);
    assert.equal(resting().length, WINDOW);
  });

  it("summarises a finished recording by averaging, not by sampling", () => {
    // Sampling makes the drawn shape depend on where the buckets happened to land, so two
    // renders at different widths disagree about where the loud part was.
    const loudThenQuiet = [1, 1, FLOOR_HEIGHT, FLOOR_HEIGHT];
    const [first, second] = summarise(loudThenQuiet, 2);
    assert.equal(first, 1);
    assert.equal(second, FLOOR_HEIGHT);
  });

  it("draws something for a recording with no stored shape at all", () => {
    assert.deepEqual(summarise([], 3), [FLOOR_HEIGHT, FLOOR_HEIGHT, FLOOR_HEIGHT]);
    assert.deepEqual(summarise([1, 1], 0), []);
  });

  it("never summarises down to an invisible row", () => {
    for (const height of summarise(resting(64), 12)) {
      assert.ok(height >= FLOOR_HEIGHT);
    }
  });

  it("shows a timer that counts up and has nothing to count down to", () => {
    assert.equal(clock(0), "0:00");
    assert.equal(clock(4.9), "0:04");
    assert.equal(clock(65), "1:05");
    assert.equal(clock(-3), "0:00");
  });
});

/**
 * TASK-713 — the first time, there is a permission sheet in the way.
 *
 * The very first press does not start a recording. It puts up the OS microphone dialog,
 * over the app, and the finger that pressed is now hovering over a system alert. Almost
 * everyone lifts it there — the button they were holding is no longer under it.
 *
 * The old code awaited the dialog and only then told the machine a press had happened, so
 * the release that came while the sheet was up landed on a machine at rest and did
 * nothing. Tap "Allow", and the phone started recording and never stopped: the parent's
 * first experience of the vault was a live microphone they did not ask for and could not
 * see how to end.
 *
 * The fix is a state, not a flag. While the sheet is up the machine is `asking`, a release
 * during it returns to rest, and an answer that arrives at rest starts nothing.
 */
describe("asking for the microphone", () => {
  it("captures nothing while the sheet is up", () => {
    const { state, effects } = gesture({ kind: "ask", at: 0 });
    assert.equal(state.phase, "asking");
    assert.deepEqual(effects, []);
    assert.equal(isLive(state), false);
  });

  it("starts recording when the answer arrives and the finger is still down", () => {
    const { state, effects } = gesture(
      { kind: "ask", at: 0 },
      { kind: "granted", at: 900 },
      { kind: "tick", at: 900 + ARMING_MS }
    );
    assert.equal(state.phase, "recording");
    assert.deepEqual(effects, ["start"]);
  });

  it("arms from the answer rather than from the press", () => {
    // The 200ms is there to tell a tap from a hold. Measuring it from a press that was
    // three seconds ago means the first recording starts the instant permission lands,
    // which is the one recording most likely to be an accident.
    const { state } = gesture({ kind: "ask", at: 0 }, { kind: "granted", at: 3000 });
    assert.equal(state.phase, "arming");
    assert.equal(state.pressedAt, 3000);
  });

  it("cancels the arm when the finger lifts during the sheet", () => {
    const { state, effects } = gesture({ kind: "ask", at: 0 }, { kind: "release", at: 400 });
    assert.deepEqual(state, RESTING);
    assert.deepEqual(effects, []);
  });

  it("starts nothing when permission is granted after the finger has lifted", () => {
    // The whole bug, as one sequence. This is what left a first-time parent recording.
    const { state, effects } = gesture(
      { kind: "ask", at: 0 },
      { kind: "release", at: 400 },
      { kind: "granted", at: 900 },
      { kind: "tick", at: 900 + ARMING_MS },
      { kind: "tick", at: 5000 }
    );
    assert.deepEqual(state, RESTING);
    assert.deepEqual(effects, []);
  });

  it("returns to rest when permission is refused", () => {
    const { state, effects } = gesture({ kind: "ask", at: 0 }, { kind: "refused" });
    assert.deepEqual(state, RESTING);
    assert.deepEqual(effects, []);
  });

  it("says nothing alarming to a screen reader while it waits", () => {
    assert.equal(announce("asking"), "Hold to talk.");
  });
});

describe("the recorder holds the gesture, not a promise", () => {
  it("never signals a press from inside an await", () => {
    const source = readFileSync(
      new URL("../src/components/HoldToTalk.tsx", import.meta.url),
      "utf8"
    );
    // `signal("press")` after `await requestRecordingPermissionsAsync()` is the shape of
    // the bug: by then the release has already happened and been ignored.
    assert.ok(
      !/await requestRecordingPermissionsAsync[\s\S]{0,400}?signal\("press"\)/.test(source),
      "the press is still signalled after the permission dialog resolves"
    );
    assert.match(source, /signal\("ask"\)/);
    assert.match(source, /signal\("granted"\)|signal\("refused"\)/);
  });
});
