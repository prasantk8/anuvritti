/**
 * Where a launch goes, and what a revoked token means (TASK-513).
 *
 * The app had a pairing screen that nothing pointed at. Every launch opened Today, and on a
 * phone that had never paired, Today made two calls that came back 401 and rendered "Nothing
 * today. That's normal." — which is a sentence about a family's week, shown to someone who
 * does not yet have a family on this server. There was no route to the one screen that
 * would have fixed it. The screen existed; the graph did not.
 *
 * So the decision lives here rather than in a `useEffect` inside a component: it is a
 * decision, it is three lines, and `test/threshold.test.ts` can walk the whole route graph
 * without a simulator. The rule that catches the next one is not this function — it is the
 * reachability test beside it, which fails when any route under `app/` has nothing pointing
 * at it.
 */

import type { Failure } from "@anuvritti/client";

/**
 * What this device knows about itself.
 *
 * `unknown` is a real state and not a loading spinner in disguise: reading the keychain is
 * asynchronous, and the frame before it answers must not be Today (a flash of an empty
 * archive) or pairing (a flash of "Start our family" at someone who did, two years ago).
 */
export type Standing = "unknown" | "paired" | "unpaired";

/** The whole route graph above the screens: wait, pair, or the app. */
export type Start =
  | { readonly kind: "wait" }
  | { readonly kind: "pair" }
  | { readonly kind: "home" };

export function whereToStart(standing: Standing): Start {
  switch (standing) {
    case "unknown":
      return { kind: "wait" };
    case "unpaired":
      return { kind: "pair" };
    case "paired":
      return { kind: "home" };
    default: {
      const exhaustive: never = standing;
      return exhaustive;
    }
  }
}

/**
 * Whether a failure means this device is no longer paired.
 *
 * Deliberately only 401, and deliberately not 403. A 403 is a device that *is* paired and
 * was refused one particular thing; signing it out would turn "you may not revoke the
 * owner" into "you are not in this family any more". The manual checklist has "revoke the
 * second device from the first — the second is signed out on its next call", and 401 is the
 * only status that carries that.
 *
 * `offline` and `timeout` are not this either. A phone in a basement is still paired.
 */
export function noLongerPaired(failure: Failure): boolean {
  return failure.kind === "api" && failure.status === 401;
}

/**
 * A `fetch` that notices its own revocation.
 *
 * The alternative was for every screen to check every call, which means the one screen
 * added next year does not. This wraps the transport's single seam instead — the one place
 * in the app where an HTTP status actually exists — and it is a wrapper rather than an
 * interceptor chain because there is exactly one thing to notice and it should stay that
 * way.
 *
 * It reports; it does not act. Clearing the keychain is the provider's job, and the
 * distinction matters because the queue must survive: a parent who captured five things on
 * a plane and lands to a revoked token has five things worth keeping and one credential
 * worth throwing away.
 */
export function noticingRevocation(
  inner: typeof globalThis.fetch,
  onRevoked: () => void
): typeof globalThis.fetch {
  return async (input, init) => {
    const response = await inner(input, init);
    if (response.status === 401) onRevoked();
    return response;
  };
}

