/**
 * TASK-713 — a recording of a parent's voice is never lost, and never doubled.
 *
 * The capture queue (TASK-509) already made *captures* durable, and it could not do the
 * same for the bytes: it stores JSON in SQLite and a four-second recording is not JSON.
 * So `keepRecording` uploaded synchronously and, when the upload failed, returned a
 * failure and left the file wherever `expo-audio` had put it — the cache directory, which
 * iOS empties whenever it likes. The parent was told "Still on your phone", and on a bad
 * enough day that was not true.
 *
 * The spool closes it. Three promises, and each one is a test below:
 *
 * **It is written down before it is sent.** Spooling is a file move and one row. No
 * network, so nothing about it can be slow (PRD §8.2), and nothing about a dead network
 * can make it fail.
 *
 * **It survives the app dying.** The row is SQLite and the file is in the app's own
 * document directory. Whatever was half-done resumes from what is written down.
 *
 * **The bytes go up exactly once.** The media id is written to the row the instant the
 * upload returns, so a resumed spool never uploads twice; and the follow-on capture is
 * queued under the *spool's* id, so replaying it is the same entry rather than a second
 * recording of the same four seconds.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { Clock, QueuedCapture, Random, Result } from "@anuvritti/client";
import { createQueue, err, memoryQueueStore, ok } from "@anuvritti/client";

import type { Custody, Follow, SpoolStore, Spooled } from "../src/upload/spool.ts";
import { createOutbox, memorySpoolStore } from "../src/upload/spool.ts";

const VOICE: Follow = { kind: "voice", seconds: 4.2 };
const PHOTO: Follow = {
  kind: "spark",
  media: {
    uri: "file:///shared/IMG_4021.HEIC",
    mimeType: "image/heic",
    kind: "PHOTO",
    name: "IMG_4021.HEIC",
  },
};

/** A clock that only moves when a test says so. */
function stopped(at = 1_000): Clock & { advance(by: number): void } {
  let now = at;
  return {
    now: () => now,
    advance(by) {
      now += by;
    },
  };
}

/** Ids that are readable in a failure message, and jitter that is not random. */
function counted(): Random {
  let n = 0;
  return {
    next: () => 1,
    id: () => `id-${(n += 1)}`,
  };
}

/** A document directory, as two Maps: where everything came from, and what is still there. */
function custody(): Custody & {
  readonly origin: Map<string, string>;
  readonly held: Set<string>;
  readonly released: string[];
} {
  const origin = new Map<string, string>();
  const held = new Set<string>();
  const released: string[] = [];
  return {
    origin,
    held,
    released,
    async keep(uri, id, extension) {
      const kept = `file:///documents/outbox/${id}${extension}`;
      origin.set(kept, uri);
      held.add(kept);
      return kept;
    },
    async release(uri) {
      released.push(uri);
      held.delete(uri);
    },
  };
}

interface Bench {
  readonly store: SpoolStore;
  readonly clock: ReturnType<typeof stopped>;
  readonly files: ReturnType<typeof custody>;
  readonly sent: QueuedCapture[];
  readonly uploaded: Spooled[];
  outbox(over?: Partial<Parameters<typeof createOutbox>[0]>): ReturnType<typeof createOutbox>;
  queued(): Promise<readonly QueuedCapture[]>;
}

/**
 * Everything wired the way it is on a phone, with the network and the disk replaced.
 *
 * The queue is the *real* one from `@anuvritti/client`, because the exactly-once promise
 * is a promise about how the spool and the queue meet, and a fake queue would let the
 * spool's half of it pass while the phone still made two recordings out of one.
 */
function bench(upload?: (entry: Spooled) => Promise<Result<{ readonly id: string }>>): Bench {
  const store = memorySpoolStore();
  const clock = stopped();
  const random = counted();
  const files = custody();
  const sent: QueuedCapture[] = [];
  const uploaded: Spooled[] = [];
  const queueStore = memoryQueueStore();

  const queue = createQueue({
    store: queueStore,
    clock,
    random,
    send: async (entry) => {
      sent.push(entry);
      return ok({});
    },
  });

  const uploads = upload ?? (async () => ok({ id: `med-${uploaded.length}` }));

  return {
    store,
    clock,
    files,
    sent,
    uploaded,
    queued: () => queue.pending(),
    outbox: (over = {}) =>
      createOutbox({
        store,
        clock,
        random,
        queue,
        custody: files,
        upload: async (entry) => {
          uploaded.push(entry);
          return uploads(entry);
        },
        ...over,
      }),
  };
}

describe("spooling is not sending", () => {
  it("writes the recording down and returns, without touching the network", async () => {
    const rig = bench();
    const outbox = rig.outbox();

    await outbox.spool({ uri: "file:///cache/rec.m4a", mimeType: "audio/mp4" }, VOICE);

    assert.equal(rig.uploaded.length, 0, "spooling reached the network");
    assert.equal((await outbox.pending()).length, 1);
  });

  it("takes the file into the app's own keeping first", async () => {
    // `expo-audio` writes into the cache directory, which iOS empties under pressure and
    // without asking. A spool entry pointing there is a promise the OS can break.
    const rig = bench();
    const outbox = rig.outbox();

    const entry = await outbox.spool(
      { uri: "file:///cache/rec.m4a", mimeType: "audio/mp4" },
      VOICE
    );

    assert.ok(!entry.uri.includes("/cache/"), `left in the cache: ${entry.uri}`);
    assert.equal(rig.files.origin.get(entry.uri), "file:///cache/rec.m4a");
  });

  it("keeps the extension, because the server reads the name", async () => {
    const rig = bench();
    const entry = await rig
      .outbox()
      .spool({ uri: "file:///cache/rec.m4a", mimeType: "audio/mp4" }, VOICE);

    assert.ok(entry.uri.endsWith(".m4a"), entry.uri);
    assert.ok(entry.name.endsWith(".m4a"), entry.name);
  });
});

describe("a dead network delays a recording and never loses it", () => {
  it("leaves it spooled, with a later time to try again", async () => {
    const rig = bench(async () => err({ kind: "offline", message: "no route to host" }));
    const outbox = rig.outbox();
    await outbox.spool({ uri: "file:///cache/rec.m4a", mimeType: "audio/mp4" }, VOICE);

    const report = await outbox.drain();

    assert.equal(report.sent, 0);
    assert.equal(report.waiting, 1);
    const [pending] = await outbox.pending();
    assert.equal(pending?.attempts, 1);
    assert.ok(pending!.nextAttemptAt > rig.clock.now(), "it would try again immediately");
    assert.equal(rig.files.released.length, 0, "the file was let go while still unsent");
  });

  it("sends it when the signal comes back", async () => {
    let online = false;
    const rig = bench(async () =>
      online ? ok({ id: "med-1" }) : err({ kind: "offline", message: "no route to host" })
    );
    const outbox = rig.outbox();
    await outbox.spool({ uri: "file:///cache/rec.m4a", mimeType: "audio/mp4" }, VOICE);
    await outbox.drain();

    online = true;
    rig.clock.advance(60_000);
    const report = await outbox.drain();

    assert.equal(report.sent, 1);
    assert.equal((await outbox.pending()).length, 0);
    assert.equal(rig.files.released.length, 1, "the file was kept after it was safely up");
  });

  it("does not burn the whole backlog against a network that is still gone", async () => {
    const rig = bench(async () => err({ kind: "timeout", message: "no answer" }));
    const outbox = rig.outbox();
    await outbox.spool({ uri: "file:///cache/one.m4a", mimeType: "audio/mp4" }, VOICE);
    await outbox.spool({ uri: "file:///cache/two.m4a", mimeType: "audio/mp4" }, VOICE);

    await outbox.drain();

    assert.equal(rig.uploaded.length, 1, "it tried every entry against a dead network");
  });
});

describe("exactly once", () => {
  it("does not upload the bytes again after the app is killed mid-keep", async () => {
    // The app dies between the upload returning and the note being queued. On the next
    // launch the media id is already written down, so the four seconds go up once.
    const rig = bench();
    const brokenQueue = {
      enqueue: async () => {
        throw new Error("the app was killed");
      },
      drain: async () => ({ sent: 0, waiting: 0, abandoned: [] }),
      pending: async () => [],
    };

    const dying = rig.outbox({ queue: brokenQueue });
    await dying.spool({ uri: "file:///cache/rec.m4a", mimeType: "audio/mp4" }, VOICE);
    await assert.rejects(() => dying.drain());

    const relaunched = rig.outbox();
    const report = await relaunched.drain();

    assert.equal(rig.uploaded.length, 1, "the same recording was uploaded twice");
    assert.equal(report.sent, 1);
    assert.equal((await rig.queued()).length, 1);
  });

  it("queues the note under the spool's own id, so a replay is the same note", async () => {
    // The other half of the same window: killed *after* the note was queued and before
    // the spool row was removed. Re-queueing under the same id is an update, not a second
    // recording of the same four seconds.
    const rig = bench();
    let refuse = true;
    const flaky: SpoolStore = {
      append: (entry) => rig.store.append(entry),
      replace: (entry) => rig.store.replace(entry),
      list: () => rig.store.list(),
      remove: async (id) => {
        if (refuse) throw new Error("the app was killed");
        await rig.store.remove(id);
      },
    };

    const dying = rig.outbox({ store: flaky });
    const entry = await dying.spool({ uri: "file:///cache/rec.m4a", mimeType: "audio/mp4" }, VOICE);
    await assert.rejects(() => dying.drain());

    refuse = false;
    await rig.outbox({ store: flaky }).drain();

    const queued = await rig.queued();
    assert.equal(queued.length, 1, "one recording became two notes");
    assert.equal(queued[0]?.id, entry.id, "the note is not keyed to the recording it came from");
  });
});

describe("what the server will never accept", () => {
  it("stops trying, says so, and still does not delete the file", async () => {
    const rig = bench(async () =>
      err({
        kind: "api",
        status: 415,
        code: "UNSUPPORTED_MEDIA_TYPE",
        message: "that is not audio",
        details: {},
      })
    );
    const outbox = rig.outbox();
    await outbox.spool({ uri: "file:///cache/rec.m4a", mimeType: "audio/mp4" }, VOICE);

    const report = await outbox.drain();

    assert.equal(report.sent, 0);
    assert.equal(report.refused.length, 1);
    assert.equal(report.refused[0]?.failure.kind, "api");
    assert.equal((await outbox.pending()).length, 0, "it will retry a 415 forever");
    assert.equal(
      rig.files.released.length,
      0,
      "the only copy of a recording was deleted because the server refused it"
    );
  });
});

describe("what a spooled file becomes", () => {
  it("a recording becomes a voice note with its length", async () => {
    const rig = bench();
    const outbox = rig.outbox();
    await outbox.spool({ uri: "file:///cache/rec.m4a", mimeType: "audio/mp4" }, VOICE);
    await outbox.drain();

    const [queued] = await rig.queued();
    assert.equal(queued?.operation, "keepVoiceNote");
    assert.deepEqual(queued?.body, { media_id: "med-1", duration_seconds: 4.2 });
  });

  it("a shared photograph becomes a Spark that points at its bytes", async () => {
    const rig = bench();
    const outbox = rig.outbox();
    await outbox.spool({ uri: "file:///shared/IMG_4021.HEIC", mimeType: "image/heic" }, PHOTO);
    await outbox.drain();

    const [queued] = await rig.queued();
    assert.equal(queued?.operation, "captureSpark");
    assert.deepEqual(queued?.body, {
      source: { kind: "PHOTO", media_id: "med-1", title: "IMG_4021.HEIC" },
    });
  });

  it("sends the oldest first, so a family's day replays in order", async () => {
    const rig = bench();
    const outbox = rig.outbox();
    await outbox.spool({ uri: "file:///cache/one.m4a", mimeType: "audio/mp4" }, VOICE);
    rig.clock.advance(1_000);
    await outbox.spool({ uri: "file:///cache/two.m4a", mimeType: "audio/mp4" }, VOICE);

    await outbox.drain();

    assert.deepEqual(
      rig.uploaded.map((entry) => rig.files.origin.get(entry.uri) ?? entry.uri),
      ["file:///cache/one.m4a", "file:///cache/two.m4a"]
    );
  });
});
