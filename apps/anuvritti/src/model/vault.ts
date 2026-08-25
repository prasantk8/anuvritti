/**
 * Little Things, and the seed of the Papa Voice Vault (TASK-605; PRD §17, §21).
 *
 * ## The reason to record
 *
 * PRD §17 asks for something trivially easy: "he called the elevator an alligator", said
 * out loud, no script, no polish. The hard part is not the button. The hard part is that
 * recording one sentence about your own child feels faintly ridiculous, and a product that
 * cannot answer *why am I doing this* gets used twice.
 *
 * The answer is Phase 7: every clip becomes a line in this year's film. So the app says so,
 * once, at the moment it is most true — right after a recording is kept. Not as a progress
 * bar, not as "3 clips towards your film", not as anything a parent could be behind on.
 * One sentence, stated in the present tense, and then the screen gets out of the way.
 *
 * ## The shelf has no count
 *
 * The vault is where the constitution is most under pressure, because a list of recordings
 * is *begging* for a number at the top. There isn't one here, and `shelve` is written so
 * there is nowhere to put one: it returns periods holding recordings, and neither the
 * period nor the shelf carries a length that means anything other than "how many rows to
 * draw". The tests check the shape, not just the copy.
 *
 * Pure, and imports only a type.
 */

import type { VoiceNote } from "@anuvritti/client";

/**
 * What the app says after a recording is kept.
 *
 * Present tense and finished. "That's in this year's film" is true the moment it is said —
 * Phase 7 compiles from what is already in the archive — so it is a statement rather than
 * a promise, and nothing has to be done to make it come true.
 */
export const KEPT = "That's in this year's film.";

/**
 * What the app says when the vault is empty.
 *
 * No call to action, because a call to action here is a chore. It says what the shelf is
 * for and stops.
 */
export const NOTHING_YET = "Nothing here yet. This is where his father's voice lives.";

/**
 * Things worth saying out loud, offered one at a time when someone opens the recorder cold.
 *
 * Every one is a *noticing*, never an assessment — the same rule `RIGHT_NOW_PROMPTS` holds
 * on the server. None of them asks a parent to be wise, which is the failure mode PRD §17
 * names directly: "No need to sound wise."
 */
export const WORTH_SAYING = [
  "What did he say today that you want to keep?",
  "What word does he say wrong in a way you hope he never fixes?",
  "What happened today that you'd have told your own father about?",
  "What made you both laugh?",
  "What is he like at the moment, in one sentence?",
  "What do you want him to know, that you'd struggle to say to his face?",
  "What did he do that you didn't expect?",
  "What is the most ordinary thing about today?",
] as const;

/**
 * The prompt for a given day. Deterministic, and the same all day.
 *
 * A prompt that changes on every open is a slot machine; one that changes daily is a
 * question someone actually gets to sit with. The rotation matches the server's Right Now
 * prompt for the same reason and by the same arithmetic.
 *
 * It takes an ISO date string rather than a `Date`, and reads it with `slice`. That is the
 * same discipline `packages/client` enforces with a test (TASK-507): once a timestamp is a
 * `Date`, subtracting two of them is one keystroke away, and a day count about a family's
 * own life is the one number this product must never hand an interface. A rotation index
 * needs an ordinal, not a duration, so it is built from the digits and cannot become one.
 */
export function worthSayingOn(isoDate: string): string {
  const year = Number(isoDate.slice(0, 4));
  const month = Number(isoDate.slice(5, 7));
  const day = Number(isoDate.slice(8, 10));
  if (!year || !month || !day) return WORTH_SAYING[0];
  const ordinal = year * 372 + month * 31 + day;
  return WORTH_SAYING[ordinal % WORTH_SAYING.length]!;
}

export interface Period {
  /** "August 2026". A month, because a year is too coarse and a day is a diary. */
  readonly named: string;
  readonly recordings: readonly VoiceNote[];
}

/**
 * The vault, grouped into months, newest first.
 *
 * Grouped by *when it was recorded* rather than by topic, because the vault is not a
 * library and nobody is looking for a subject. They are looking for a time: what he sounded
 * like the year the child started school.
 *
 * The server already returns newest-first. This preserves that order rather than re-sorting,
 * for the same reason `whatToBringBack` does not re-rank: the ordering is the server's
 * answer and a second opinion here would only ever be a bug.
 */
export function shelve(recordings: readonly VoiceNote[]): readonly Period[] {
  const periods: Period[] = [];
  for (const recording of recordings) {
    const named = monthOf(recording.recorded_at);
    const current = periods[periods.length - 1];
    if (current && current.named === named) {
      periods[periods.length - 1] = {
        named,
        recordings: [...current.recordings, recording],
      };
    } else {
      periods.push({ named, recordings: [recording] });
    }
  }
  return periods;
}

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
] as const;

/**
 * The month an ISO timestamp falls in, read as characters rather than parsed.
 *
 * `packages/client` forbids `Date.parse` and `new Date` for a reason that applies here too
 * (TASK-507): once a timestamp is a `Date`, subtracting two of them is one keystroke away,
 * and a day count is the one number this product must never hand an interface. Slicing
 * `"2026-08-25T..."` gives a label and nothing that can be subtracted.
 */
function monthOf(instant: string): string {
  const year = instant.slice(0, 4);
  const month = Number(instant.slice(5, 7));
  const named = MONTHS[month - 1];
  return named ? `${named} ${year}` : year;
}
