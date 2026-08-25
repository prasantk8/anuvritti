/**
 * The capture queue (TASK-509).
 *
 * PRD §11 gives capture ten seconds, and the underground does not care. So capture never
 * waits for the network: it writes to a durable local queue and returns, and "Saved." is
 * the truth because the queue is durable, not because a server said so.
 *
 * Three rules, and every one of them exists because the obvious alternative loses a memory:
 *
 * **Enqueue is never gated on connectivity.** No "try the network for two seconds, then
 * fall back". A captive portal or a black-holed IPv6 route hangs TCP connect for the full
 * OS timeout - 75 seconds on iOS - and the ten-second budget is gone. Connectivity is a
 * hint about *when to drain*, never a condition on saving.
 *
 * **Every entry carries its idempotency key from the moment it is written.** Not generated
 * at send time: the whole point is that a replay after an unknown outcome is safe, and a
 * fresh key on the second attempt would create a second Spark.
 *
 * **Failure is classified, not counted.** A 422 will fail identically forever, so retrying
 * it is a loop that never ends and never tells anyone. It leaves the queue and is surfaced.
 *
 * Storage is a port. On device it is SQLite in the App Group container, so the share
 * extension and the app write the same queue; in tests it is a Map.
 */

import type { Clock, Failure, Random, Result } from "./types.ts";
import { err, isRetryable, ok } from "./types.ts";

/** Operations a queue may hold: the ones the contract marks replayable. */
export type QueueableOperation =
  | "captureSpark"
  | "captureLittleThing"
  | "captureRightNow"
  | "markAsDone";

export interface QueuedCapture {
  /** Also the `Idempotency-Key`. One identity for the thing, wherever it is. */
  readonly id: string;
  readonly operation: QueueableOperation;
  /** Path parameters, in the order the operation declares them. */
  readonly pathArgs: readonly string[];
  readonly body: unknown;
  readonly enqueuedAt: number;
  readonly attempts: number;
  readonly nextAttemptAt: number;
  readonly lastError?: string;
}

/** Durable storage for pending captures. */
export interface QueueStore {
  append(entry: QueuedCapture): Promise<void>;
  replace(entry: QueuedCapture): Promise<void>;
  remove(id: string): Promise<void>;
  /** Oldest first. A family's captures replay in the order they happened. */
  list(): Promise<readonly QueuedCapture[]>;
}

/** What a drain did, in the terms the interface would want to say something about. */
export interface DrainReport {
  readonly sent: number;
  readonly waiting: number;
  readonly abandoned: readonly { readonly entry: QueuedCapture; readonly failure: Failure }[];
}

/** First retry after a second; then two, four, eight, up to five minutes. */
export const BASE_BACKOFF_MS = 1_000;
export const MAX_BACKOFF_MS = 5 * 60 * 1_000;

/**
 * Exponential, with full jitter.
 *
 * The jitter is not decoration. Without it every capture queued during one outage retries
 * at exactly the same moment when the signal returns, and a family's phone hits the server
 * with the whole backlog in one burst - a self-inflicted thundering herd of one device.
 */
export function backoffMs(attempts: number, random: Random): number {
  const ceiling = Math.min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * 2 ** Math.max(0, attempts - 1));
  return Math.round(random.next() * ceiling);
}

export interface QueueConfig {
  readonly store: QueueStore;
  readonly clock: Clock;
  readonly random: Random;
  /**
   * Perform one entry against the network. Injected rather than importing the client, so a
   * test can drive the whole queue without a transport and so the share extension can pass
   * a send that uses a background session.
   */
  readonly send: (entry: QueuedCapture) => Promise<Result<unknown>>;
}

export interface CaptureQueue {
  /** Write and return. Never touches the network. */
  enqueue(
    operation: QueueableOperation,
    body: unknown,
    pathArgs?: readonly string[]
  ): Promise<QueuedCapture>;
  /** Attempt everything that is due. Safe to call often; safe to call with no signal. */
  drain(): Promise<DrainReport>;
  pending(): Promise<readonly QueuedCapture[]>;
}

export function createQueue(config: QueueConfig): CaptureQueue {
  const { store, clock, random, send } = config;

  async function enqueue(
    operation: QueueableOperation,
    body: unknown,
    pathArgs: readonly string[] = []
  ): Promise<QueuedCapture> {
    const now = clock.now();
    const entry: QueuedCapture = {
      id: random.id(),
      operation,
      pathArgs,
      body,
      enqueuedAt: now,
      attempts: 0,
      nextAttemptAt: now,
    };
    await store.append(entry);
    return entry;
  }

  async function drain(): Promise<DrainReport> {
    const now = clock.now();
    const abandoned: DrainReport["abandoned"] = [];
    let sent = 0;
    let waiting = 0;

    for (const entry of await store.list()) {
      if (entry.nextAttemptAt > now) {
        waiting += 1;
        continue;
      }

      const result = await send(entry);
      if (result.ok) {
        await store.remove(entry.id);
        sent += 1;
        continue;
      }

      if (!isRetryable(result.error)) {
        // It will fail the same way forever. Leaving it in would be a queue that never
        // empties and never says why.
        await store.remove(entry.id);
        abandoned.push({ entry, failure: result.error });
        continue;
      }

      const attempts = entry.attempts + 1;
      await store.replace({
        ...entry,
        attempts,
        nextAttemptAt: now + backoffMs(attempts, random),
        lastError: describe(result.error),
      });
      waiting += 1;

      // Stop on the first retryable failure. The next entry would almost certainly fail
      // the same way, and burning the whole backlog against a dead network costs battery
      // and teaches the server nothing.
      break;
    }

    return { sent, waiting, abandoned };
  }

  return { enqueue, drain, pending: () => store.list() };
}

function describe(failure: Failure): string {
  return failure.kind === "api" ? `${failure.code}: ${failure.message}` : failure.message;
}

/** A queue store held in memory. For tests, and for nothing else - it is not durable. */
export function memoryQueueStore(): QueueStore {
  const entries = new Map<string, QueuedCapture>();
  return {
    async append(entry) {
      entries.set(entry.id, entry);
    },
    async replace(entry) {
      entries.set(entry.id, entry);
    },
    async remove(id) {
      entries.delete(id);
    },
    async list() {
      return [...entries.values()].sort((a, b) => a.enqueuedAt - b.enqueuedAt);
    },
  };
}

export { err, ok };
