/**
 * One-tap correction (TASK-510).
 *
 * The machine guessed `WATCH` and it was really `DO`. The parent taps the chip and it says
 * `DO`. That is the whole interaction, and the design constraint is stated as a negative
 * because that is where products fail: **the chip never becomes a form.** No modal, no
 * picker sheet, no "edit details", no Save button. Tap, and it is different.
 *
 * That has a consequence worth stating: cycling can only work over a small, ordered,
 * complete set. Six intents is small enough that the right one is at most five taps away
 * and usually one. This is why PRD §48 F4 ships six rather than ten - the number was chosen
 * so this gesture could exist.
 *
 * The order is not alphabetical and not the enum's declaration order. It is *likelihood
 * given what the machine already thought*, so the first tap is usually the answer: a thing
 * mistaken for `WATCH` is nearly always a `DO`.
 *
 * The domain already models the rest. Overriding sets `Attributed.human_override`, and a
 * human-set field is never re-inferred, so a correction survives every later pass.
 */

import type { Contract, IntentType, Spark } from "../generated/contract.ts";
import { INTENT_TYPE_VALUES } from "../generated/contract.ts";
import type { CallOptions, Result } from "./types.ts";
import { intentOf } from "./attributed.ts";

/**
 * Where to go next from each intent, ordered by what the mistake usually was.
 *
 * Every list is a permutation of the full set, so the cycle always terminates back where it
 * started and a parent can never reach a state they cannot leave. The test asserts that.
 */
export const NEXT_INTENT: Readonly<Record<IntentType, readonly [IntentType, ...IntentType[]]>> = {
  DO: ["WATCH", "TEACH", "COOK", "VISIT", "BUY", "READ", "TELL", "LISTEN", "REMEMBER"],
  WATCH: ["READ", "LISTEN", "TELL", "DO", "TEACH", "COOK", "VISIT", "BUY", "REMEMBER"],
  BUY: ["DO", "COOK", "VISIT", "READ", "WATCH", "TEACH", "TELL", "LISTEN", "REMEMBER"],
  READ: ["TELL", "LISTEN", "TEACH", "WATCH", "DO", "COOK", "VISIT", "BUY", "REMEMBER"],
  TEACH: ["TELL", "DO", "READ", "LISTEN", "COOK", "VISIT", "WATCH", "BUY", "REMEMBER"],
  REMEMBER: ["DO", "WATCH", "READ", "TEACH", "COOK", "VISIT", "TELL", "LISTEN", "BUY"],
  COOK: ["DO", "BUY", "TEACH", "VISIT", "WATCH", "READ", "TELL", "LISTEN", "REMEMBER"],
  VISIT: ["DO", "BUY", "COOK", "WATCH", "READ", "TEACH", "TELL", "LISTEN", "REMEMBER"],
  TELL: ["LISTEN", "READ", "TEACH", "DO", "WATCH", "COOK", "VISIT", "BUY", "REMEMBER"],
  LISTEN: ["TELL", "WATCH", "READ", "TEACH", "DO", "COOK", "VISIT", "BUY", "REMEMBER"],
};

/** How the intents are said to a parent. Verbs, because an intent is something you will do. */
export const INTENT_SAID: Readonly<Record<IntentType, string>> = {
  DO: "do together",
  BUY: "buy",
  WATCH: "watch",
  READ: "read",
  TEACH: "teach",
  REMEMBER: "remember",
  COOK: "cook",
  VISIT: "visit",
  TELL: "tell",
  LISTEN: "listen",
};

/** The next intent one tap away. Wraps, so the cycle is closed. */
export function nextIntent(current: IntentType): IntentType {
  // No fallback, because `NEXT_INTENT` is typed as a non-empty list per intent and the
  // compiler now knows it. The `?? INTENT_TYPE_VALUES[0]` that used to sit here was
  // unreachable, and unreachable code on this path would have silently changed a parent's
  // correction into `DO`.
  return NEXT_INTENT[current][0];
}

/**
 * The full cycle from a starting point, in tap order.
 *
 * Exposed so an interface can show what is coming without guessing, and so the test can
 * assert that every cycle visits all six exactly once.
 */
export function intentCycle(start: IntentType): readonly IntentType[] {
  const seen: IntentType[] = [start];
  let current = start;
  for (let step = 0; step < INTENT_TYPE_VALUES.length - 1; step += 1) {
    const next = NEXT_INTENT[current].find((candidate) => !seen.includes(candidate));
    if (!next) break;
    seen.push(next);
    current = next;
  }
  return seen;
}

/**
 * Tap the chip.
 *
 * Optimistic on purpose: the chip changes immediately and the request follows. A parent who
 * has to wait for a server before the word changes will tap twice, and the second tap is a
 * correction of the correction.
 */
export interface Correction {
  /** What the chip should say now, before anything has been sent. */
  readonly optimistic: IntentType;
  /** What the server made of it. */
  readonly confirmed: Promise<Result<Spark>>;
}

export function correctIntent(
  api: Contract,
  spark: Spark,
  options?: CallOptions
): Correction | null {
  const current = intentOf(spark);
  if (!current) return null;

  const next = nextIntent(current.value);
  return {
    optimistic: next,
    confirmed: api.overrideField(spark.id, { field: "intent", value: next }, options),
  };
}
