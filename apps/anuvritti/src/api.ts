/**
 * The one place the app is wired to a server.
 *
 * Everything platform-specific converges here: where the token lives, where the queue lives,
 * where randomness comes from. `@anuvritti/client` declares all three as ports precisely so
 * this file is the only one that knows about `expo-*`, and so the client's own tests need no
 * device.
 */

import * as Crypto from "expo-crypto";

import type { CaptureQueue, Clock, QueuedCapture, Random, Result } from "@anuvritti/client";
import { createClient, createQueue } from "@anuvritti/client";

import { noticingRevocation } from "./model/threshold.ts";
import { sqliteQueueStore } from "./storage/queue-store.ts";
import { secureTokenStore } from "./storage/token-store.ts";

/**
 * `expo-crypto`, and nothing else.
 *
 * Hermes ships no Web Crypto: `globalThis.crypto.randomUUID` and `crypto.getRandomValues`
 * are both absent, which is why `uuid@>=7` and `nanoid` break on React Native. The Hermes
 * team closed the request as out of scope for a JS engine. `Crypto.randomUUID()` is
 * synchronous and native-backed, and `react-native-get-random-values` is not needed on top.
 *
 * `Math.random()` would work here and must not be used: an idempotency key that collides is
 * a capture silently answered with a different capture's response.
 */
const random: Random = {
  next: () => {
    const bytes = Crypto.getRandomValues(new Uint8Array(4));
    return ((bytes[0]! << 24) >>> 0) / 0x1_0000_0000;
  },
  id: () => Crypto.randomUUID(),
};

const clock: Clock = { now: () => Date.now() };

export interface Wired {
  readonly anuvritti: ReturnType<typeof createClient>;
  readonly queue: CaptureQueue;
}

export interface Wiring {
  /**
   * Called when the server answers 401 — this device's token is no longer good.
   *
   * Passed in rather than handled here because the response is a routing decision, and this
   * file's whole job is to know about `expo-*` so that nothing else has to.
   */
  readonly onRevoked?: () => void;
}

/**
 * Build the client and the queue.
 *
 * The queue's `send` closes over the client, which is what makes a queued entry replay as
 * exactly the call it would have been — with its own id as the idempotency key, so the
 * replay is safe whatever happened to the first attempt.
 */
export async function wire(baseUrl: string, wiring: Wiring = {}): Promise<Wired> {
  const tokens = secureTokenStore();
  const anuvritti = createClient({
    baseUrl,
    tokens,
    clock,
    // The transport is the only place in the app where an HTTP status exists, so it is the
    // only honest place to notice a revoked token. One wrapper, not an interceptor chain.
    fetch: wiring.onRevoked
      ? noticingRevocation(globalThis.fetch, wiring.onRevoked)
      : undefined,
  });
  const store = await sqliteQueueStore();

  const send = (entry: QueuedCapture): Promise<Result<unknown>> => {
    const options = { idempotencyKey: entry.id };
    switch (entry.operation) {
      case "captureSpark":
        return anuvritti.api.captureSpark(entry.body as never, options);
      case "captureLittleThing":
        return anuvritti.api.captureLittleThing(entry.body as never, options);
      case "captureRightNow":
        return anuvritti.api.captureRightNow(entry.body as never, options);
      case "keepVoiceNote":
        // Replayable for the same reason a capture is, and more urgently: the phone that
        // held the button has already released its audio buffer, so a retry that created a
        // second note would be the only copy of the mistake.
        return anuvritti.api.keepVoiceNote(entry.body as never, options);
      case "markAsDone":
        return anuvritti.api.markAsDone(entry.pathArgs[0]!, entry.body as never, options);
      default: {
        // A new queueable operation added to the client and forgotten here is a compile
        // error, not an entry that silently never sends.
        const exhaustive: never = entry.operation;
        return exhaustive;
      }
    }
  };

  return { anuvritti, queue: createQueue({ store, clock, random, send }) };
}

export { random as deviceRandom, clock as deviceClock };
