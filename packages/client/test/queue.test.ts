/**
 * TASK-509 — the capture queue.
 *
 * Every test here is a real moment on a real phone: the underground, the lift, the school
 * car park with one bar. The queue's job is that none of those moments loses a memory, and
 * that a parent never waits for a network to find out whether something was saved.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { QueueConfig } from "../src/index.ts";
import {
  BASE_BACKOFF_MS,
  MAX_BACKOFF_MS,
  backoffMs,
  createQueue,
  err,
  memoryQueueStore,
  ok,
} from "../src/index.ts";
import { fixedRandom, frozenClock } from "./support.ts";

const REEL = { source: { kind: "URL", url: "https://instagram.com/reel/balloon" } };

// The queue's own port, not `ReturnType<typeof ok>` — which resolves to
// `Result<unknown, never>` and so contextually typed every `err({ kind: "offline" })`
// in this file as an error that could not exist. Nothing said so until the repository
// grew a typechecker.
function queueWith(send: QueueConfig["send"]) {
  const clock = frozenClock();
  const random = fixedRandom(0.5);
  const store = memoryQueueStore();
  return { clock, random, store, queue: createQueue({ store, clock, random, send }) };
}

const alwaysOffline = async () => err({ kind: "offline" as const, message: "no signal" });
const alwaysAccepted = async () => ok({ id: "sp-1" });

describe("saving never waits for a network", () => {
  it("enqueues without making a single call", async () => {
    let calls = 0;
    const { queue } = queueWith(async () => {
      calls += 1;
      return ok({});
    });

    await queue.enqueue("captureSpark", REEL);
    assert.equal(calls, 0, "capture has ten seconds; a captive portal takes seventy-five");
    assert.equal((await queue.pending()).length, 1);
  });

  it("gives the capture its idempotency key at the moment it is written", async () => {
    const { queue, random } = queueWith(alwaysAccepted);
    const entry = await queue.enqueue("captureSpark", REEL);

    assert.equal(entry.id, random.ids[0]);
    // Generating it at send time instead would mean a replay after an unknown outcome
    // arrives with a fresh key, and the family gets the same Spark twice.
    assert.equal(entry.attempts, 0);
  });

  it("keeps captures in the order they happened", async () => {
    const { queue, clock } = queueWith(alwaysAccepted);
    await queue.enqueue("captureSpark", { source: { kind: "TEXT", text: "first" } });
    clock.advance(1_000);
    await queue.enqueue("captureSpark", { source: { kind: "TEXT", text: "second" } });

    const pending = await queue.pending();
    assert.deepEqual(
      pending.map((entry) => (entry.body as { source: { text: string } }).source.text),
      ["first", "second"]
    );
  });
});

describe("draining", () => {
  it("sends what is due and forgets it", async () => {
    const { queue } = queueWith(alwaysAccepted);
    await queue.enqueue("captureSpark", REEL);

    const report = await queue.drain();
    assert.equal(report.sent, 1);
    assert.equal((await queue.pending()).length, 0);
  });

  it("sends the same entry with the same key every time it retries", async () => {
    const keys: string[] = [];
    let firstAttempt = true;
    const attempted = queueWith(async (entry) => {
      keys.push(entry.id);
      if (firstAttempt) {
        firstAttempt = false;
        return err({ kind: "offline", message: "no signal" });
      }
      return ok({});
    });

    await attempted.queue.enqueue("captureSpark", REEL);
    await attempted.queue.drain();
    attempted.clock.advance(MAX_BACKOFF_MS);
    await attempted.queue.drain();

    assert.equal(keys.length, 2);
    assert.equal(keys[0], keys[1], "a fresh key on the retry would create a second Spark");
    assert.equal((await attempted.queue.pending()).length, 0);
  });

  it("holds a failed capture and tries again later", async () => {
    const { queue, clock } = queueWith(alwaysOffline);
    await queue.enqueue("captureSpark", REEL);

    const first = await queue.drain();
    assert.equal(first.sent, 0);
    assert.equal(first.waiting, 1);

    // Immediately again: it is not due yet, so nothing is attempted.
    const tooSoon = await queue.drain();
    assert.equal(tooSoon.waiting, 1);

    clock.advance(MAX_BACKOFF_MS);
    const pending = await queue.pending();
    assert.equal(pending[0]?.attempts, 1);
    assert.match(pending[0]?.lastError ?? "", /no signal/);
  });

  it("stops at the first retryable failure rather than burning the backlog", async () => {
    let attempts = 0;
    const { queue } = queueWith(async () => {
      attempts += 1;
      return err({ kind: "offline", message: "no signal" });
    });

    for (let index = 0; index < 5; index += 1) {
      await queue.enqueue("captureSpark", REEL);
    }
    await queue.drain();

    assert.equal(attempts, 1, "the next four would fail identically and cost battery");
    assert.equal((await queue.pending()).length, 5);
  });

  it("does not lose the rest of the queue when one entry is unsendable", async () => {
    const { queue } = queueWith(async (entry) => {
      const body = entry.body as { source?: { text?: string } };
      if (body.source?.text === "broken") {
        return err({ kind: "api", status: 422, code: "VALIDATION_FAILED", message: "bad", details: {} });
      }
      return ok({});
    });

    await queue.enqueue("captureSpark", { source: { kind: "TEXT", text: "broken" } });
    await queue.enqueue("captureSpark", { source: { kind: "TEXT", text: "fine" } });

    const report = await queue.drain();
    assert.equal(report.abandoned.length, 1);
    assert.equal(report.sent, 1);
    assert.equal((await queue.pending()).length, 0);
  });
});

describe("failure is classified, not counted", () => {
  it("abandons a request that will fail identically forever", async () => {
    const { queue } = queueWith(async () =>
      err({ kind: "api", status: 422, code: "CAPTURE_SOURCE_INVALID", message: "bad url", details: {} })
    );
    await queue.enqueue("captureSpark", REEL);

    const report = await queue.drain();
    assert.equal(report.abandoned.length, 1);
    assert.equal(report.abandoned[0]?.failure.kind, "api");
    assert.equal(
      (await queue.pending()).length,
      0,
      "a queue that retries a 422 never empties and never says why"
    );
  });

  it("retries a server that asked for time", async () => {
    for (const status of [429, 500, 503]) {
      const { queue } = queueWith(async () =>
        err({ kind: "api", status, code: "CONFLICT", message: "later", details: {} })
      );
      await queue.enqueue("captureSpark", REEL);
      const report = await queue.drain();
      assert.equal(report.waiting, 1, `${status} should be retried`);
      assert.equal(report.abandoned.length, 0);
    }
  });

  it("abandons a reused key, because that is a bug in this client", async () => {
    // Our server stores a fingerprint of the request beside the key, so a 409 here means
    // the same key went out with a different body. Retrying cannot fix that.
    const { queue } = queueWith(async () =>
      err({ kind: "api", status: 409, code: "CONFLICT", message: "key reused", details: {} })
    );
    await queue.enqueue("captureSpark", REEL);
    assert.equal((await queue.drain()).abandoned.length, 1);
  });
});

describe("backoff", () => {
  it("grows, and stops growing", () => {
    const random = fixedRandom(1);
    assert.equal(backoffMs(1, random), BASE_BACKOFF_MS);
    assert.equal(backoffMs(2, random), BASE_BACKOFF_MS * 2);
    assert.equal(backoffMs(4, random), BASE_BACKOFF_MS * 8);
    assert.equal(backoffMs(50, random), MAX_BACKOFF_MS);
  });

  it("is jittered across its whole range", () => {
    // Without jitter every capture queued during one outage retries at the same instant
    // when the signal returns - a thundering herd of one phone.
    assert.equal(backoffMs(4, fixedRandom(0)), 0);
    assert.equal(backoffMs(4, fixedRandom(1)), BASE_BACKOFF_MS * 8);
    assert.equal(backoffMs(4, fixedRandom(0.5)), BASE_BACKOFF_MS * 4);
  });
});
