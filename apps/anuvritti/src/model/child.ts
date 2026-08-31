/**
 * Child View logic (TASK-818, PRD 19, PRD 63.6).
 *
 * One single chosen piece of media handed to a child at bedtime:
 * - Tonight's song, a voice note from a grandparent, or a single scene from the film.
 * - Plays once.
 * - When playback ends: transitions immediately to complete stillness and darkness.
 * - Zero recommendations, zero autoplay, zero 'next up', zero engagement loops.
 * - Exit back to parent interface requires parent PIN verification.
 */

export interface ChildBedtimeMedia {
  readonly id: string;
  readonly title: string;
  readonly type: "song" | "voice_note" | "scene";
  readonly mediaId: string;
  readonly authorName?: string;
}

export type ChildViewState =
  | { readonly kind: "ready"; readonly media: ChildBedtimeMedia }
  | { readonly kind: "playing"; readonly media: ChildBedtimeMedia }
  | { readonly kind: "finished_dark" };

export const BEDTIME_GOODNIGHT_TEXT = "Goodnight. Sleep tight.";

export function transitionOnPlaybackEnd(current: ChildViewState): ChildViewState {
  return { kind: "finished_dark" };
}

export function isScreenStill(state: ChildViewState): boolean {
  return state.kind === "finished_dark";
}

export function verifyParentPin(entered: string, correctPin: string): boolean {
  if (!entered || !correctPin) return false;
  return entered.trim() === correctPin.trim();
}

