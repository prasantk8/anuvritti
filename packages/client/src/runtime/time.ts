/**
 * Time as language (TASK-507).
 *
 * This module's most important property is what it does not contain. There is no function
 * here that turns an `Instant` into a `Date`, a number of milliseconds, or a difference.
 * Not because someone would do it maliciously - because "247" is right there in
 * `created_at`, the design says "8 months ago", and the deadline is Friday.
 *
 * So the server sends the phrase and this package cannot compute one. `packages/client`
 * contains no `Date.parse`, no `new Date(...)`, no `getTime()`, and a test asserts it.
 *
 * Ordering still works. Two ISO-8601 timestamps in the same offset - which is all this
 * server emits, always UTC - sort correctly as plain strings. That is not a trick to avoid
 * the rule; it is a comparison that structurally cannot produce a quantity.
 */

import type { Elapsed, Instant } from "../generated/contract.ts";

export type { Elapsed, Instant };

/**
 * Order two instants, newest last. Returns -1, 0 or 1 and never a duration.
 *
 * Valid because the server writes every timestamp as UTC with a fixed-width offset, so
 * lexicographic order is chronological order. If that ever stopped being true the fix is on
 * the server, not a `Date` here.
 */
export function compareInstants(a: Instant, b: Instant): -1 | 0 | 1 {
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

/** Newest first, which is how a vault is read. */
export function newestFirst<T extends { readonly created_at: Instant }>(
  items: readonly T[]
): readonly T[] {
  return [...items].sort((a, b) => -compareInstants(a.created_at, b.created_at));
}

/**
 * Read a phrase the server sent.
 *
 * The only way to obtain an `Elapsed`. There is deliberately no `elapsedSince(instant)`:
 * a client that could produce one could produce "247 days" from it.
 */
export function asElapsed(fromServer: string): Elapsed {
  return fromServer as Elapsed;
}

/**
 * The phrase as a sentence opener, so the interface never assembles one from parts.
 *
 * "8 months ago" becomes "You saved this 8 months ago."; "today" becomes "You saved this
 * today." The special case exists because "You saved this today ago." is what string
 * concatenation produces if nobody looks.
 */
export function savedSentence(elapsed: Elapsed): string {
  return `You saved this ${elapsed}.`;
}

/**
 * Whether a phrase describes something recent enough to be worth a lighter treatment.
 *
 * Matched on the words rather than on a duration, because the words are all there is. This
 * is the only place in the interface that branches on time at all, and it can distinguish
 * exactly three cases - which is the intended ceiling on how much the design may know.
 */
export function nearness(elapsed: Elapsed): "today" | "recent" | "a while ago" {
  const said = String(elapsed);
  if (said === "today" || said === "yesterday") return "today";
  if (said.includes("day") || said.includes("week")) return "recent";
  return "a while ago";
}
