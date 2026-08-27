/**
 * The one place the app is wired to a server.
 *
 * Everything platform-specific converges here: where the token lives, where the queue lives,
 * where randomness comes from. `@anuvritti/client` declares all three as ports precisely so
 * this file is the only one that knows about `expo-*`, and so the client's own tests need no
 * device.
 */

import * as Crypto from "expo-crypto";

import type {
  CaptureQueue,
  Clock,
  QueuedCapture,
  Random,
  Result,
  TokenStore,
} from "@anuvritti/client";
import { createClient, createQueue } from "@anuvritti/client";

import { sqliteQueueStore } from "./storage/queue-store.ts";
import { documentCustody, sqliteSpoolStore } from "./storage/spool-store.ts";
import { secureTokenStore } from "./storage/token-store.ts";
import type { Outbox, Spooled } from "./upload/spool.ts";
import { createOutbox } from "./upload/spool.ts";

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
  /** Files that are on this phone and not yet in the archive (TASK-713). */
  readonly outbox: Outbox;
  /** The keychain, so the audio player can be handed the same bearer token (`media.ts`). */
  readonly tokens: TokenStore;
}

/**
 * Build the client and the queue.
 *
 * The queue's `send` closes over the client, which is what makes a queued entry replay as
 * exactly the call it would have been — with its own id as the idempotency key, so the
 * replay is safe whatever happened to the first attempt.
 */
export async function wire(baseUrl: string): Promise<Wired> {
  const tokens = secureTokenStore();
  const anuvritti = createClient({ baseUrl, tokens, clock });
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

  const queue = createQueue({ store, clock, random, send });

  /**
   * One multipart `POST /v1/media`.
   *
   * `FormData` with a `{ uri, name, type }` part is React Native's own extension: the
   * runtime streams the file off disk rather than reading it into JavaScript. A `Blob`
   * here would load a whole recording into memory on a phone that has just been holding a
   * microphone open, and Hermes has no `File` at all.
   */
  const upload = (entry: Spooled): Promise<Result<{ id: string }>> => {
    const form = new FormData();
    form.append("file", {
      uri: entry.uri,
      name: entry.name,
      type: entry.mimeType,
    } as unknown as Blob);
    return anuvritti.api.uploadMedia(form);
  };

  const outbox = createOutbox({
    store: await sqliteSpoolStore(),
    clock,
    random,
    queue,
    custody: documentCustody(),
    upload,
  });

  return { anuvritti, queue, outbox, tokens };
}

export { random as deviceRandom, clock as deviceClock };
