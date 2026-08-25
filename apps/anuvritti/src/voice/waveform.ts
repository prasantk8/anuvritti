/**
 * The live waveform (TASK-601).
 *
 * The waveform is not decoration. It is the only evidence a person has that the microphone
 * is actually working, and the whole reason hold-to-talk feels safe rather than uncertain.
 * So the rules here are about *trust*, not about looking nice.
 *
 * ## Silence is still a shape
 *
 * `expo-audio` reports metering in dBFS: roughly -160 for silence, 0 for clipping, and
 * about -30 to -10 for someone speaking normally into a phone. Mapping that range linearly
 * to a bar height produces a line that is flat at zero whenever nobody is talking, and a
 * flat line reads as *it stopped recording*. A parent pausing to think would then start
 * again louder, or stop and check, which is the opposite of what a five-second why needs.
 *
 * So there is a floor. Quiet is small, never nothing.
 *
 * ## dBFS is logarithmic and so is hearing
 *
 * The useful range is compressed into the top 60dB. Below that is room tone. Mapping
 * [-60, 0] rather than [-160, 0] is what makes a normal speaking voice fill most of the
 * bar height instead of a twentieth of it.
 *
 * Pure, and imports nothing.
 */

/** Below this, it is room tone. Everything quieter looks the same, because it sounds it. */
export const FLOOR_DB = -60;

/** The smallest bar. Quiet is small; nothing is never nothing. */
export const FLOOR_HEIGHT = 0.06;

/** How many bars the live waveform holds. About four seconds at a 60ms poll. */
export const WINDOW = 64;

/**
 * One metering reading, as a bar height between `FLOOR_HEIGHT` and 1.
 *
 * `undefined` is accepted because it is what `RecorderState.metering` is until the first
 * poll lands, and on any platform where metering is unavailable. The waveform still draws
 * — at the floor — rather than disappearing, because a missing meter is not a missing
 * microphone and the interface must not imply that it is.
 */
export function heightOf(decibels: number | undefined): number {
  if (decibels === undefined || Number.isNaN(decibels)) return FLOOR_HEIGHT;
  const clamped = Math.min(0, Math.max(FLOOR_DB, decibels));
  const level = (clamped - FLOOR_DB) / -FLOOR_DB;
  return FLOOR_HEIGHT + level * (1 - FLOOR_HEIGHT);
}

/**
 * Add a reading and drop the oldest, keeping the window fixed.
 *
 * A new array each time rather than a mutated one: this feeds React state, and a mutated
 * array is a waveform that does not re-render until something else happens to.
 */
export function push(
  bars: readonly number[],
  decibels: number | undefined,
  capacity: number = WINDOW
): readonly number[] {
  const next = [...bars, heightOf(decibels)];
  return next.length <= capacity ? next : next.slice(next.length - capacity);
}

/**
 * A window that is full from the first frame, so the waveform never grows in from the left.
 *
 * A bar count that climbs while someone is speaking looks like buffering. Starting full at
 * the floor and scrolling means the shape moves the moment the voice does.
 */
export function resting(capacity: number = WINDOW): readonly number[] {
  return Array.from({ length: capacity }, () => FLOOR_HEIGHT);
}

/**
 * The stored shape for a finished recording, at whatever width the row can afford.
 *
 * Averaged rather than sampled. Sampling picks a single reading per bucket, which on a
 * four-second clip means the drawn shape depends on where the buckets happened to land —
 * two renders of the same recording at different widths would disagree about where the
 * loud part was.
 */
export function summarise(bars: readonly number[], into: number): readonly number[] {
  if (into <= 0) return [];
  if (bars.length === 0) return Array.from({ length: into }, () => FLOOR_HEIGHT);

  const out: number[] = [];
  for (let index = 0; index < into; index += 1) {
    const from = Math.floor((index * bars.length) / into);
    const to = Math.max(from + 1, Math.floor(((index + 1) * bars.length) / into));
    const slice = bars.slice(from, to);
    const mean = slice.reduce((total, value) => total + value, 0) / slice.length;
    out.push(Math.max(FLOOR_HEIGHT, mean));
  }
  return out;
}

/**
 * Seconds as a timer reads them: `0:04`.
 *
 * Deliberately not "4 seconds so far" and deliberately not counting down from anything.
 * There is no limit to count down to, and a countdown would turn a five-second target into
 * a five-second deadline.
 */
export function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(whole / 60);
  return `${minutes}:${String(whole % 60).padStart(2, "0")}`;
}
