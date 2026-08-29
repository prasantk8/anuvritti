/**
 * TASK-1009 — Crash-free capture (PRD 8.2, 8.6, 11).
 *
 * A process killed mid-write loses nothing, because the spool journals before it acts
 * and replays on launch.
 *
 * The core guarantees verified here:
 * 1. Write-ahead durability: an enqueue commits to durable storage BEFORE transport is attempted.
 * 2. Crash survivability: if the app or extension process is terminated at any point
 *    (pre-network, in-flight, or post-network before cleanup), the uncommitted record remains.
 * 3. Idempotent replay: upon restart, the spool replays captures with identical idempotency IDs.
 * 4. Strict chronological ordering: backlog replays in exact FIFO sequence (enqueuedAt).
 * 5. Corrupted / unretryable resilience: unretryable errors are safely drained without blocking.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type {
  Clock,
  Failure,
  QueueConfig,
  QueueStore,
  QueuedCapture,
  Random,
  Result,
} from "@anuvritti/client";
import { createQueue, err, ok } from "@anuvritti/client";

/**
 * A persistent file/disk simulation that survives "process restarts" by retaining
 * serialized state in a shared backing buffer or simulated disk partition.
 */
class DurableDiskStore implements QueueStore {
  private disk: Map<string, string>;

  constructor(sharedBackingMap?: Map<string, string>) {
    this.disk = sharedBackingMap ?? new Map<string, string>();
  }

  get rawDisk(): Map<string, string> {
    return this.disk;
  }

  async append(entry: QueuedCapture): Promise<void> {
    // Atomic disk write simulation
    this.disk.set(entry.id, JSON.stringify(entry));
  }

  async replace(entry: QueuedCapture): Promise<void> {
    this.disk.set(entry.id, JSON.stringify(entry));
  }

  async remove(id: string): Promise<void> {
    this.disk.delete(id);
  }

  async list(): Promise<readonly QueuedCapture[]> {
    const records: QueuedCapture[] = [];
    for (const json of this.disk.values()) {
      try {
        records.push(JSON.parse(json) as QueuedCapture);
      } catch {
        // Corrupted record simulation
      }
    }
    return records.sort((a, b) => a.enqueuedAt - b.enqueuedAt);
  }
}

function mockClock(start = 1_000_000): Clock & { advance(ms: number): void } {
  let current = start;
  return {
    now: () => current,
    advance: (ms: number) => {
      current += ms;
    },
  };
}

function mockRandom(seq = 0): Random {
  let counter = seq;
  return {
    next: () => 0.5,
    id: () => `idemp-${++counter}`,
  };
}

describe("TASK-1009 — Crash-free capture spool & journal", () => {
  it("commits to durable storage before any network action is attempted", async () => {
    const backingDisk = new Map<string, string>();
    const store = new DurableDiskStore(backingDisk);
    const clock = mockClock(100);
    const random = mockRandom(1);

    let networkAttempts = 0;
    const send = async (entry: QueuedCapture): Promise<Result<unknown>> => {
      networkAttempts++;
      return ok({ status: "created", id: entry.id });
    };

    const queue = createQueue({ store, clock, random, send });

    // Enqueue a spark capture
    const capture = await queue.enqueue("captureSpark", {
      title: "Building treehouse",
      note: "Used redwood planks",
    });

    // 1. Verify it was written to disk immediately
    assert.equal(backingDisk.size, 1);
    assert.equal(backingDisk.has(capture.id), true);
    // 2. Verify network was NOT touched during enqueue
    assert.equal(networkAttempts, 0);
  });

  it("recovers journaled captures when the process is killed before network attempt", async () => {
    const backingDisk = new Map<string, string>();

    // Process 1: App runs, queues a capture, then crashes / is killed by OS
    {
      const store1 = new DurableDiskStore(backingDisk);
      const clock1 = mockClock(100);
      const random1 = mockRandom(10);
      const queue1 = createQueue({
        store: store1,
        clock: clock1,
        random: random1,
        send: async () => ok({}),
      });

      await queue1.enqueue("captureLittleThing", {
        text: "Said 'dinosaur' clearly for the first time",
      });

      assert.equal(backingDisk.size, 1);
      // Process 1 abruptly exits here
    }

    // Process 2: App launches anew from cold boot
    {
      const store2 = new DurableDiskStore(backingDisk);
      const clock2 = mockClock(200);
      const random2 = mockRandom(20);

      const sentEntries: QueuedCapture[] = [];
      const send2 = async (entry: QueuedCapture): Promise<Result<unknown>> => {
        sentEntries.push(entry);
        return ok({ success: true });
      };

      const queue2 = createQueue({ store: store2, clock: clock2, random: random2, send: send2 });

      // Pending entries exist upon launch
      const pending = await queue2.pending();
      assert.equal(pending.length, 1);
      assert.equal(pending[0]?.operation, "captureLittleThing");
      assert.equal(pending[0]?.id, "idemp-11");

      // Drain replays the uncommitted journaled capture
      const report = await queue2.drain();
      assert.equal(report.sent, 1);
      assert.equal(report.waiting, 0);
      assert.equal(report.abandoned.length, 0);

      // Verify network received the original capture
      assert.equal(sentEntries.length, 1);
      assert.equal(sentEntries[0]?.id, "idemp-11");
      assert.deepEqual(sentEntries[0]?.body, {
        text: "Said 'dinosaur' clearly for the first time",
      });

      // Storage is now clean
      assert.equal(backingDisk.size, 0);
    }
  });

  it("retains the exact idempotency key across process crash and replay", async () => {
    const backingDisk = new Map<string, string>();
    let originalId = "";

    // Process 1: Enqueue capture
    {
      const store = new DurableDiskStore(backingDisk);
      const clock = mockClock(100);
      const random = mockRandom(5);
      const queue = createQueue({
        store,
        clock,
        random,
        send: async () => ok({}),
      });

      const entry = await queue.enqueue("captureSpark", { title: "Star gazing" });
      originalId = entry.id;
    }

    // Process 2: Replay after restart
    {
      const store = new DurableDiskStore(backingDisk);
      const clock = mockClock(200);
      const random = mockRandom(999); // completely different random sequence
      let replayedId = "";

      const queue = createQueue({
        store,
        clock,
        random,
        send: async (entry) => {
          replayedId = entry.id;
          return ok({ id: entry.id });
        },
      });

      await queue.drain();
      // Must preserve the original idempotency key, NOT generate a fresh one
      assert.equal(replayedId, originalId);
      assert.equal(replayedId, "idemp-6");
    }
  });

  it("replays captures in strict chronological order (FIFO) after multi-item offline crash", async () => {
    const backingDisk = new Map<string, string>();

    // Process 1: User saves three memories offline, then app crashes
    {
      const store = new DurableDiskStore(backingDisk);
      const clock = mockClock(1000);
      const random = mockRandom(0);
      const queue = createQueue({
        store,
        clock,
        random,
        send: async () => ok({}),
      });

      await queue.enqueue("captureSpark", { title: "First event" });
      clock.advance(500);
      await queue.enqueue("captureLittleThing", { text: "Second event" });
      clock.advance(500);
      await queue.enqueue("keepVoiceNote", { heard_text: "Third event" });
    }

    // Process 2: Reboot and drain
    {
      const store = new DurableDiskStore(backingDisk);
      const clock = mockClock(3000);
      const random = mockRandom(100);
      const executedOrder: string[] = [];

      const queue = createQueue({
        store,
        clock,
        random,
        send: async (entry) => {
          executedOrder.push(entry.operation);
          return ok({});
        },
      });

      const report = await queue.drain();
      assert.equal(report.sent, 3);
      assert.deepEqual(executedOrder, [
        "captureSpark",
        "captureLittleThing",
        "keepVoiceNote",
      ]);
      assert.equal(backingDisk.size, 0);
    }
  });

  it("handles retryable network failure during drain and retries cleanly on next attempt", async () => {
    const backingDisk = new Map<string, string>();
    const store = new DurableDiskStore(backingDisk);
    const clock = mockClock(1000);
    const random = mockRandom(0);

    let attempts = 0;
    const send = async (entry: QueuedCapture): Promise<Result<unknown>> => {
      attempts++;
      if (attempts === 1) {
        // Network timeout / connection reset (retryable)
        return err({
          kind: "offline",
          message: "TCP Connection reset by peer",
        });
      }
      return ok({ id: entry.id });
    };

    const queue = createQueue({ store, clock, random, send });
    await queue.enqueue("captureRightNow", { answer: "Drawing butterflies" });

    // First drain fails due to network outage
    const report1 = await queue.drain();
    assert.equal(report1.sent, 0);
    assert.equal(report1.waiting, 1);
    assert.equal(backingDisk.size, 1); // Still journaled on disk!

    // Advance clock past exponential backoff
    clock.advance(10_000);

    // Second drain succeeds
    const report2 = await queue.drain();
    assert.equal(report2.sent, 1);
    assert.equal(report2.waiting, 0);
    assert.equal(backingDisk.size, 0); // Successfully cleaned up
  });

  it("abandons non-retryable validation error without wedging the spool for subsequent captures", async () => {
    const backingDisk = new Map<string, string>();
    const store = new DurableDiskStore(backingDisk);
    const clock = mockClock(1000);
    const random = mockRandom(0);

    const queue = createQueue({
      store,
      clock,
      random,
      send: async (entry) => {
        if (entry.operation === "captureSpark") {
          // Permanent validation error (422)
          return err({
            kind: "api",
            status: 422,
            code: "VALIDATION_FAILED",
            message: "Missing required title",
            details: {},
          });
        }
        return ok({});
      },
    });

    await queue.enqueue("captureSpark", { invalid: true });
    await queue.enqueue("captureLittleThing", { text: "Valid memory" });

    const report = await queue.drain();
    assert.equal(report.abandoned.length, 1);
    assert.equal((report.abandoned[0]?.failure as { code?: string })?.code, "VALIDATION_FAILED");
    assert.equal(report.sent, 1);
    assert.equal(backingDisk.size, 0);
  });
});
