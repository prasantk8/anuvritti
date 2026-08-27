/**
 * Hold to talk (TASK-601).
 *
 * A pure state machine, importing nothing. Everything about *recording* is native and
 * untestable off a device — the session category, the encoder, the permission dialog. What
 * a press and a release *mean* is neither, so it lives here and it is tested.
 *
 * ## Five seconds is the target, not a minimum
 *
 * PRD §12 says the answer may be only five seconds, and PRD §24 says nothing is rejected
 * for being unpolished. Those two together rule out the obvious implementation, which is a
 * minimum duration to stop stray taps creating empty notes. There is no minimum here and
 * `tests/constitution/test_preserve_imperfection.py` scans for one.
 *
 * The stray tap is a real problem and it is solved one step earlier. The machine has an
 * **arming** state: a press does not start recording, it starts a 200ms clock, and only
 * when that clock runs out does audio begin. A tap therefore never produces a recording —
 * not a discarded one, not a short one, none. The threshold filters the *gesture*; once
 * audio exists it is kept, whatever is on it and however long it lasts.
 *
 * That distinction is the whole design. It is also why there is no slide-to-cancel: the
 * cancel gesture exists to throw away a recording that already happened, which is the one
 * thing this file is built to make impossible.
 *
 * ## The first press is not a press (TASK-713)
 *
 * The very first time, the press puts up the OS microphone dialog instead of starting
 * anything. The button a parent is holding is now under a system alert, and almost everyone
 * lifts their finger there. The answer — "Allow" — then arrives on a phone nobody is
 * touching, and treating it as the start of a hold left a first-time user recording, with
 * no visible way to stop.
 *
 * So asking is a **state**, not a flag. A release during it goes back to rest, and an answer
 * that arrives at rest starts nothing. The arming clock is measured from the *answer*, not
 * from the press it followed: the 200ms exists to tell a tap from a hold, and a threshold
 * measured from three seconds ago has already elapsed.
 *
 * ## Interruptions keep what was said
 *
 * A phone call during a recording ends it, and ending it means **keeping** it. The
 * alternative — treating an interruption as an abandonment — loses four seconds of a
 * parent's voice to an incoming spam call, and there is no way to ask for them back.
 */

/** How long a press must be held before any audio is captured. */
export const ARMING_MS = 200;

/**
 * The intention behind the number: five seconds is what PRD §12 expects a why to be. It is
 * a target for the copy and the layout, never a gate, and nothing in this file reads it.
 */
export const TYPICAL_SECONDS = 5;

export type Phase =
  /** Nothing is happening. */
  | "resting"
  /** The OS is asking about the microphone. Held, but the finger is over a system alert. */
  | "asking"
  /** Held, but not yet long enough to be meant. No audio exists. */
  | "arming"
  /** Audio is being captured. */
  | "recording"
  /** Released. What was captured is being kept. */
  | "keeping";

export interface Recording {
  readonly phase: Phase;
  /** When the press began, in the caller's clock. */
  readonly pressedAt: number;
  /** When audio actually began. Zero until it does. */
  readonly startedAt: number;
  /** Set only in `keeping`, and it is what gets saved. */
  readonly seconds: number;
}

export const RESTING: Recording = {
  phase: "resting",
  pressedAt: 0,
  startedAt: 0,
  seconds: 0,
};

export type Signal =
  | { readonly kind: "press"; readonly at: number }
  /** The permission sheet went up. Nothing is being captured behind it. */
  | { readonly kind: "ask"; readonly at: number }
  /** The parent allowed it. Only means anything if the finger is still down. */
  | { readonly kind: "granted"; readonly at: number }
  /** The parent did not. */
  | { readonly kind: "refused" }
  | { readonly kind: "tick"; readonly at: number }
  | { readonly kind: "release"; readonly at: number }
  /** The system took the microphone away: a call, another app, a media-services reset. */
  | { readonly kind: "interrupted"; readonly at: number }
  /** The keep finished, successfully or not. Either way this gesture is over. */
  | { readonly kind: "settled" };

/**
 * What the caller must do next, if anything.
 *
 * Returned rather than performed, so this file stays pure and the component that owns the
 * native recorder is the only thing that touches it.
 */
export type Effect = "start" | "stop" | "keep" | "none";

export interface Step {
  readonly state: Recording;
  readonly effect: Effect;
}

/**
 * Advance the machine.
 *
 * `at` is supplied by the caller rather than read from a clock, for the same reason the
 * server takes a `Clock`: a state machine that reads the time cannot be tested without
 * waiting, and a test that waits is a test that gets deleted.
 */
export function step(state: Recording, signal: Signal): Step {
  switch (state.phase) {
    case "resting":
      if (signal.kind === "press") {
        return {
          state: { phase: "arming", pressedAt: signal.at, startedAt: 0, seconds: 0 },
          effect: "none",
        };
      }
      if (signal.kind === "ask") {
        return {
          state: { phase: "asking", pressedAt: signal.at, startedAt: 0, seconds: 0 },
          effect: "none",
        };
      }
      // A `granted` that lands here is a permission answer for a finger that has already
      // lifted. It starts nothing — which is the entire point of this state existing.
      return { state, effect: "none" };

    case "asking":
      if (signal.kind === "granted") {
        // Armed from the answer, not from the press: see the note at the top of the file.
        return {
          state: { ...state, phase: "arming", pressedAt: signal.at },
          effect: "none",
        };
      }
      if (signal.kind === "refused" || signal.kind === "release" || signal.kind === "interrupted") {
        // Nothing was ever captured behind a permission sheet, so nothing is thrown away.
        return { state: RESTING, effect: "none" };
      }
      return { state, effect: "none" };

    case "arming":
      if (signal.kind === "tick" && signal.at - state.pressedAt >= ARMING_MS) {
        return {
          state: { ...state, phase: "recording", startedAt: signal.at },
          effect: "start",
        };
      }
      if (signal.kind === "release" || signal.kind === "interrupted") {
        // A tap. No audio was ever captured, so nothing is being thrown away — which is
        // the only reason this branch is allowed to exist at all.
        return { state: RESTING, effect: "none" };
      }
      return { state, effect: "none" };

    case "recording":
      if (signal.kind === "release" || signal.kind === "interrupted") {
        return {
          state: {
            ...state,
            phase: "keeping",
            seconds: elapsedSeconds(state.startedAt, signal.at),
          },
          effect: signal.kind === "release" ? "stop" : "keep",
        };
      }
      return { state, effect: "none" };

    case "keeping":
      // Every path out of `keeping` returns to rest. There is no failure branch that
      // discards the audio: a save that could not reach the server goes to the offline
      // queue, which is what `src/api.ts` is for.
      return signal.kind === "settled" ? { state: RESTING, effect: "none" } : { state, effect: "none" };
  }
}

/**
 * How long a recording in progress has been going, for the timer under the waveform.
 *
 * Zero while arming, which is correct and not a rounding artefact: nothing has been
 * recorded yet, so nothing has a length.
 */
export function elapsed(state: Recording, now: number): number {
  if (state.phase === "recording") return elapsedSeconds(state.startedAt, now);
  if (state.phase === "keeping") return state.seconds;
  return 0;
}

/** Whether the microphone is live, which is what the interface must never be vague about. */
export function isLive(state: Recording): boolean {
  return state.phase === "recording";
}

/**
 * What to announce to a screen reader.
 *
 * Spoken rather than shown, because the visible state of this control is a waveform and a
 * waveform says nothing to VoiceOver. "Recording" and "Saved" are the two facts a person
 * has an absolute right to, and neither is a status a sighted user has to infer either.
 */
export function announce(phase: Phase): string {
  switch (phase) {
    case "recording":
      return "Recording.";
    case "keeping":
      return "Saved.";
    case "asking":
    case "arming":
    case "resting":
      return "Hold to talk.";
  }
}

function elapsedSeconds(from: number, to: number): number {
  // Clamped at zero rather than trusted: a caller passing a stale timestamp should produce
  // a zero-length recording, which is kept, rather than a negative one, which the server
  // is right to refuse.
  return Math.max(0, (to - from) / 1000);
}
