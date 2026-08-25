/**
 * The recording is the artifact; the transcript is only an index (TASK-602).
 *
 * The server holds this as a data rule. This file holds it as an interface rule, and the
 * interface is where it will actually be broken, because text is so much easier to lay out.
 * A transcript is one line, wraps, truncates, searches, and fits in a list row. A player is
 * a control with a state machine, a scrubber and a duration. Every screen that has ever
 * shown both has drifted towards showing the text and hiding the audio behind a small
 * triangle, and after a year nobody plays anything.
 *
 * So `whatToShow` returns a type where the player is **not optional** and the words are.
 * There is no value of `Playback` that renders words without a player, and building one
 * would mean editing this file, which is the point.
 *
 * ## The words are labelled by who said them
 *
 * PRD §8.7 splits recorded truth from human interpretation from machine interpretation, and
 * a transcript is never the first of those. So the label is not decoration:
 *
 * * a machine reading that is confident says **"It sounded like"**;
 * * a machine reading that is not says **"Maybe"**;
 * * something a parent typed themselves is shown plainly, because it is not a guess.
 *
 * Pure, and imports only a type.
 */

import type { VoiceNote } from "@anuvritti/client";

/** Below this a reading is offered as a possibility rather than as a reading. */
export const UNSURE = 0.5;

export interface Player {
  readonly mediaId: string;
  readonly seconds: number;
}

export type Words =
  /** A machine's reading of the audio. Always hedged, and always attributed. */
  | { readonly kind: "heard"; readonly text: string; readonly said: string; readonly sure: boolean }
  /** What a person typed. Not a guess, so it carries no hedge. */
  | { readonly kind: "written"; readonly text: string };

/**
 * What a voice note looks like on screen.
 *
 * `player` first and non-nullable; `words` second and nullable. The field order in this
 * interface is not enforcement — TypeScript does not care — but the nullability is, and the
 * order is how the rule reads to the next person who opens the file.
 */
export interface Playback {
  readonly player: Player;
  readonly words: Words | null;
}

export function whatToShow(note: VoiceNote): Playback {
  return {
    player: { mediaId: note.media_id, seconds: note.duration_seconds },
    words: wordsFrom(note),
  };
}

function wordsFrom(note: VoiceNote): Words | null {
  const transcript = note.transcript;
  if (!transcript || !transcript.text.trim()) return null;

  if (transcript.source === "HUMAN") {
    return { kind: "written", text: transcript.text };
  }
  const sure = transcript.confidence >= UNSURE;
  return {
    kind: "heard",
    text: transcript.text,
    said: sure ? "It sounded like" : "Maybe",
    sure,
  };
}

/**
 * How long a recording is, said the way a person would say it.
 *
 * Rounded up, never down. "0 seconds" is a thing that did not happen, and a half-second
 * clip of someone starting to say something did.
 */
export function lengthOf(seconds: number): string {
  const whole = Math.max(1, Math.ceil(seconds));
  if (whole < 60) return `${whole} sec`;
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} sec`;
}

/**
 * What a screen reader is told about a recording.
 *
 * The transcript is read out when there is one, because for someone using VoiceOver the
 * words are not a lesser version of the audio — they are the only way to know what is in it
 * before committing to playing it. The hedge is read too: a machine's guess presented as a
 * quotation is a worse failure here than anywhere else on the screen.
 */
export function describe(playback: Playback): string {
  const length = lengthOf(playback.player.seconds);
  const words = playback.words;
  if (!words) return `Recording, ${length}.`;
  if (words.kind === "written") return `Recording, ${length}. ${words.text}`;
  return `Recording, ${length}. ${words.said}: ${words.text}`;
}

/**
 * A why that has a recording renders as the recording. Words alone render as words.
 *
 * The narrow case this exists for: a Spark's why can hold typed text, a recording, or both.
 * When it holds both, the recording leads and the text sits under it as a second, lesser
 * way of giving the same answer — never the other way round, and never instead.
 */
export function whyFrom(why: {
  text?: string | null;
  voice?: VoiceNote | null;
}): { readonly voice: Playback | null; readonly text: string | null } {
  return {
    voice: why.voice ? whatToShow(why.voice) : null,
    text: why.text?.trim() ? why.text : null,
  };
}
