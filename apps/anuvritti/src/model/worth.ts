/**
 * Worth Bringing Back, on a phone (TASK-512).
 *
 * The server already refuses to nag: it returns at most three, only for things genuinely
 * forgotten, and an empty list is a normal silent outcome. The phone narrows further, to
 * **one**, and the reason is not screen size.
 *
 * Three suggestions is a list, and a list is a queue, and a queue is something a parent is
 * behind on. One is a sentence someone said to them. The other two are not lost — they are
 * still eligible tomorrow, and the engine's novelty decay means the one shown today will
 * step aside for them. What is deliberately absent is any way to see that there were three:
 * no "2 more", no dot, no count. PRD §8.5 as an interface rule rather than a copy rule.
 *
 * Pure, and therefore tested. Everything about this that could be got wrong is a decision,
 * not a rendering.
 */

import type { Suggestion } from "@anuvritti/client";

/**
 * What the screen shows: one thing, or nothing, and never a number.
 *
 * `nothing` is not an empty state to apologise for. Most days there is nothing worth
 * interrupting a family about, and the screen should say so warmly and briefly.
 */
export type WorthBringingBack =
  | { readonly kind: "one"; readonly suggestion: Suggestion }
  | { readonly kind: "nothing" };

/**
 * Choose what to bring back.
 *
 * `dismissed` holds ids the parent has already said no to on this device. The server is told
 * too, and its answer is permanent — this exists so the card disappears on the tap rather
 * than on the next refresh, which is the difference between "taken seriously" and "ignored".
 *
 * The first eligible one is taken rather than the "best" one, because the server has already
 * ranked them and re-ranking here would be a second opinion nobody asked for.
 */
export function whatToBringBack(
  suggestions: readonly Suggestion[],
  dismissed: ReadonlySet<string> = new Set()
): WorthBringingBack {
  const first = suggestions.find((suggestion) => !dismissed.has(suggestion.spark.id));
  return first ? { kind: "one", suggestion: first } : { kind: "nothing" };
}

/**
 * The three answers, in the order they are offered.
 *
 * Not alphabetical, and not "best first". `lets_do_it` sits in the middle because putting
 * the affirmative first makes the other two read as refusals of an invitation, and the whole
 * point is that all three are equally fine answers.
 */
export const ANSWERS = [
  { action: "maybe_later", said: "Maybe later" },
  { action: "lets_do_it", said: "Let's do it" },
  { action: "not_relevant_anymore", said: "Not anymore" },
] as const;

export type Answer = (typeof ANSWERS)[number]["action"];

/**
 * What the interface says after an answer. Each one is a statement, not a confirmation.
 *
 * "Maybe later" gets real quiet — thirty days — and saying so is the difference between a
 * promise and a snooze button. "Not anymore" is permanent and says so, because a parent who
 * does not believe it will not use it.
 */
export const ACKNOWLEDGEMENT: Readonly<Record<Answer, string>> = {
  maybe_later: "Put away for a while.",
  lets_do_it: "Good. It's on the list.",
  not_relevant_anymore: "Gone. Won't come back.",
};

/**
 * When there is nothing.
 *
 * Present tense, no apology, no "check back later" — which is a request to return, and this
 * screen is not allowed to make one.
 */
export const NOTHING_TODAY = "Nothing today. That's normal.";
