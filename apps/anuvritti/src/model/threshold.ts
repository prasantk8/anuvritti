/**
 * The first run, and what a revoked token means.
 *
 * Where a launch goes used to be decided here too, by `whereToStart`. It is decided in
 * `src/session/gate.ts` now, which names a state this file could not: a phone that is
 * paired but has not yet reached its founding child and first share. The two answers were
 * written independently for TASK-513 and TASK-713 and said the same thing about two of the
 * three states; the gate says it about all four, so it is the one that survived.
 *
 * What stays here is the shape of the first run, and the single HTTP status that means this
 * device is not in the family any more.
 */

import type { Failure } from "@anuvritti/client";

/** Pure decisions for the first run: family, child, then one real share. */

export interface ThresholdMarker {
  readonly familyId: string;
  readonly childName?: string;
}

export type ThresholdStage = "child" | "share";

export function thresholdStage(marker: ThresholdMarker): ThresholdStage {
  return marker.childName ? "share" : "child";
}

/** The server issues eight Crockford characters; spacing is presentation, not identity. */
export function visiblePairingCode(value: string): string {
  return value.replace(/[^A-Z0-9]/gi, "").toUpperCase().slice(0, 8);
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
