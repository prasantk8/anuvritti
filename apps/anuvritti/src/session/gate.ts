/**
 * Which of the two apps this is (TASK-713).
 *
 * A phone that holds no device token is not a phone with an empty archive. Every call it
 * makes is answered `UNAUTHENTICATED` before it reaches the network at all — `transport.ts`
 * refuses to send one — so the home screen's own honest empty state, "Nothing today. That's
 * normal.", becomes the app claiming to have looked when it never could.
 *
 * There are therefore two apps behind one icon, and exactly one fact decides which: does
 * the keychain hold a token. That fact arrives asynchronously, so there is a third state,
 * and the third state is the one this file exists for. `null` is not "unpaired" and it is
 * not "paired": it is *not yet known*, and the correct thing to render while not knowing is
 * neither screen.
 *
 * Pure, so the rule is tested rather than trusted. `_layout.tsx` reads it and does nothing
 * else with the question.
 */

/** Where the archive is. */
export const HOME = "/" as const;

/** Where a phone goes to become part of a family. */
export const PAIR = "/pair" as const;
export const THRESHOLD = "/threshold" as const;

export type Gate =
  /** The keychain has not answered. Nothing that implies an answer may be on screen. */
  | "waiting"
  /** No token. The only screen that works without one. */
  | "pair"
  /** Paired, but the founding child and first share are not both here yet. */
  | "threshold"
  /** A token. Everything else. */
  | "home";

export function gateFor(paired: boolean | null, threshold = false): Gate {
  if (paired === null) return "waiting";
  if (!paired) return "pair";
  return threshold ? "threshold" : "home";
}

/**
 * Whether the archive's screens exist right now.
 *
 * Read by `Stack.Protected`, which is why this is a predicate rather than a redirect: a
 * redirect renders the wrong screen and then navigates away from it, and the wrong screen
 * here is a sentence telling a parent there is nothing of their child's to see.
 */
export function showsHome(gate: Gate): boolean {
  return gate === "home";
}

export function showsPairing(gate: Gate): boolean {
  return gate === "pair";
}

export function showsThreshold(gate: Gate): boolean {
  return gate === "threshold";
}
