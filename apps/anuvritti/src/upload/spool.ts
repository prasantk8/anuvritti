/**
 * The outbox: bytes that are on this phone and not yet in the archive (TASK-713).
 *
 * `packages/client`'s capture queue (TASK-509) made *captures* durable and could not do the
 * same for the things captures point at, for a plain reason: it stores JSON in SQLite, and
 * a four-second recording is not JSON. So the upload stayed synchronous, and a parent in a
 * basement got a failure and a file left wherever `expo-audio` had put it — the cache
 * directory, which iOS empties whenever it wants to and does not ask.
 *
 * This is the other half. It holds files rather than JSON, and it makes the same promise
 * the queue makes about captures: written down before it is sent, survives the app dying,
 * and lands exactly once.
 *
 * ## Written down before it is sent
 *
 * `spool()` moves the file into the app's own document directory and writes one row. No
 * network, so nothing about a dead network can make it fail and nothing about it can be
 * slow (PRD §8.2). The screen can say what it says as soon as this returns.
 *
 * ## Exactly once, and what that costs
 *
 * Two moments can be interrupted, and each is closed by writing something down before
 * moving on:
 *
 * * **After the bytes are up, before the note is queued.** The media id is written to the
 *   row the instant the upload returns, so a resumed spool skips straight past the upload.
 * * **After the note is queued, before the row is removed.** The note is queued under the
 *   *spool entry's own id*, which is also its `Idempotency-Key`. Queueing it again is the
 *   same entry — the store keys by id — and sending it again is answered by the server with
 *   the first attempt's note. So a replay is never a second recording of the same moment.
 *
 * One window is left open and it is not ours to close: an upload whose response is lost in
 * flight. `POST /v1/media` is declared non-idempotent in the contract, so a retry after an
 * unknown outcome can store the bytes twice. Duplicated *bytes* are a wasted megabyte;
 * duplicated *notes* would be a family's history saying a thing happened twice, which is
 * why the id above sits where it does. TASK-716 proposes the contract change that would
 * close the remaining half.
 *
 * ## Nothing is deleted because a server said no
 *
 * A refusal that will never change — a 415, a 413 — takes the entry out of the spool so it
 * is not retried forever, and leaves the file exactly where it is. The bytes are the only
 * copy of something that happened once.
 */

import type { CaptureQueue, Clock, Failure, QueueableOperation, Random, Result } from "@anuvritti/client";
import { backoffMs, isRetryable } from "@anuvritti/client";

import type { MediaFromShare } from "../capture/incoming.ts";
import { captureForMedia } from "../capture/incoming.ts";

/** What the spooled bytes become, once the archive has them. */
export type Follow =
  | {
      readonly kind: "voice";
      readonly seconds: number;
      readonly heard?: string;
      readonly heardConfidence?: number;
    }
  /** A shared image. What it becomes is `captureForMedia`'s decision, not this file's. */
  | { readonly kind: "spark"; readonly media: MediaFromShare };

export interface Spooled {
  /** Also the follow-on capture's id, and so its `Idempotency-Key`. */
  readonly id: string;
  /** Where the file is now: the app's own directory, never the cache. */
  readonly uri: string;
  /** What to call the part in the multipart body. The server reads the extension. */
  readonly name: string;
  readonly mimeType: string;
  readonly follow: Follow;
  readonly spooledAt: number;
  readonly attempts: number;
  readonly nextAttemptAt: number;
  /** Written the moment the bytes are up. Its presence is what makes a resume safe. */
  readonly mediaId?: string;
  readonly lastError?: string;
}

/** Durable storage for spooled files. SQLite on the phone; a Map in tests. */
export interface SpoolStore {
  append(entry: Spooled): Promise<void>;
  replace(entry: Spooled): Promise<void>;
  remove(id: string): Promise<void>;
  /** Oldest first. A family's day replays in the order it happened. */
  list(): Promise<readonly Spooled[]>;
}

/**
 * Custody of the file itself.
 *
 * A port for the same reason the stores are: taking a file into the app's keeping is
 * `expo-file-system` on a phone and a Map in a test, and neither belongs in this file.
 */
export interface Custody {
  /** Move it somewhere the OS will not reclaim. Returns where it now lives. */
  keep(uri: string, id: string, extension: string): Promise<string>;
  /** Let go of it, once its bytes are somewhere better than this phone. */
  release(uri: string): Promise<void>;
}

export interface OutboxConfig {
  readonly store: SpoolStore;
  readonly clock: Clock;
  readonly random: Random;
  /** Where the follow-on capture goes once there is a media id to point it at. */
  readonly queue: CaptureQueue;
  readonly custody: Custody;
  /** One multipart `POST /v1/media`. Injected, so this file needs no transport. */
  readonly upload: (entry: Spooled) => Promise<Result<{ readonly id: string }>>;
}

export interface SpoolReport {
  readonly sent: number;
  readonly waiting: number;
  /** Refused in a way that trying again cannot fix. The files are still on the phone. */
  readonly refused: readonly { readonly entry: Spooled; readonly failure: Failure }[];
}

/** What a caller hands over: a file that exists, and what it is. */
export interface ToSpool {
  readonly uri: string;
  readonly mimeType: string;
  /** What the share sheet called it, when it called it anything. */
  readonly name?: string;
}

export interface Outbox {
  /** Take custody and write it down. Never touches the network. */
  spool(file: ToSpool, follow: Follow): Promise<Spooled>;
  /** Send what is due. Safe to call often; safe to call with no signal. */
  drain(): Promise<SpoolReport>;
  pending(): Promise<readonly Spooled[]>;
}

export function createOutbox(config: OutboxConfig): Outbox {
  const { store, clock, random, queue, custody, upload } = config;

  async function spool(file: ToSpool, follow: Follow): Promise<Spooled> {
    const id = random.id();
    const extension = extensionOf(file.name ?? file.uri, file.mimeType);
    const uri = await custody.keep(file.uri, id, extension);
    const now = clock.now();
    const entry: Spooled = {
      id,
      uri,
      name: nameOf(file.name ?? file.uri, extension),
      mimeType: file.mimeType,
      follow,
      spooledAt: now,
      attempts: 0,
      nextAttemptAt: now,
    };
    await store.append(entry);
    return entry;
  }

  async function drain(): Promise<SpoolReport> {
    const now = clock.now();
    const refused: { entry: Spooled; failure: Failure }[] = [];
    let sent = 0;
    let waiting = 0;

    for (const spooled of await store.list()) {
      if (spooled.nextAttemptAt > now) {
        waiting += 1;
        continue;
      }

      let entry = spooled;
      let mediaId = entry.mediaId;

      if (!mediaId) {
        const uploaded = await upload(entry);

        if (!uploaded.ok) {
          if (!isRetryable(uploaded.error)) {
            // It will be refused the same way forever. Out of the spool so it is not
            // retried until the battery dies; the file stays where it is, because it is
            // the only copy of something that happened once.
            await store.remove(entry.id);
            refused.push({ entry, failure: uploaded.error });
            continue;
          }

          const attempts = entry.attempts + 1;
          await store.replace({
            ...entry,
            attempts,
            nextAttemptAt: now + backoffMs(attempts, random),
            lastError: describe(uploaded.error),
          });
          waiting += 1;
          // Stop at the first retryable failure, for the reason the capture queue stops:
          // the next file would fail the same way, and uploading a backlog into a dead
          // network costs a parent their battery and teaches the server nothing.
          break;
        }

        // The durability point. Written before anything else happens, so an app killed on
        // the next line resumes from here and never uploads these bytes twice.
        mediaId = uploaded.value.id;
        entry = { ...entry, mediaId, lastError: undefined };
        await store.replace(entry);
      }

      await queue.enqueue(operationFor(entry.follow), bodyFor(entry, mediaId), [], entry.id);
      await store.remove(entry.id);
      await custody.release(entry.uri);
      sent += 1;
    }

    return { sent, waiting, refused };
  }

  return { spool, drain, pending: () => store.list() };
}

/** Which capture the bytes turn into. */
export function operationFor(follow: Follow): QueueableOperation {
  return follow.kind === "voice" ? "keepVoiceNote" : "captureSpark";
}

/**
 * The follow-on capture's body.
 *
 * Undefined fields are dropped rather than sent as null: the contract's optional fields
 * mean "not said", and a null is a different claim.
 */
export function bodyFor(entry: Spooled, mediaId: string): unknown {
  if (entry.follow.kind === "voice") {
    return prune({
      media_id: mediaId,
      duration_seconds: entry.follow.seconds,
      heard_text: entry.follow.heard,
      heard_confidence: entry.follow.heardConfidence,
    });
  }
  return { source: prune({ ...captureForMedia(entry.follow.media, mediaId).source }) };
}

function prune<T extends Record<string, unknown>>(body: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(body).filter(([, value]) => value !== undefined)
  ) as Partial<T>;
}

/**
 * The file extension, from the name if it has one and from the type if it does not.
 *
 * Android hands over `content://` URIs with no extension at all, and the server reads the
 * extension to decide what it was sent — so guessing from the mime type is the difference
 * between a photograph being stored and a photograph being a 415.
 */
function extensionOf(nameOrUri: string, mimeType: string): string {
  const last = nameOrUri.split("/").pop() ?? "";
  const dot = last.lastIndexOf(".");
  if (dot > 0 && dot < last.length - 1) return last.slice(dot).toLowerCase();
  return EXTENSION[mimeType] ?? "";
}

const EXTENSION: Readonly<Record<string, string>> = {
  "audio/mp4": ".m4a",
  "audio/m4a": ".m4a",
  "audio/x-m4a": ".m4a",
  "audio/webm": ".webm",
  "audio/wav": ".wav",
  "audio/3gpp": ".3gp",
  "image/jpeg": ".jpg",
  "image/png": ".png",
  "image/heic": ".heic",
  "image/heif": ".heif",
  "image/webp": ".webp",
};

function nameOf(nameOrUri: string, extension: string): string {
  const last = (nameOrUri.split("/").pop() ?? "").trim();
  if (last.includes(".")) return last;
  return last ? `${last}${extension}` : `upload${extension}`;
}

function describe(failure: Failure): string {
  return failure.kind === "api" ? `${failure.code}: ${failure.message}` : failure.message;
}

/** A spool held in memory. For tests, and for nothing else — it is not durable. */
export function memorySpoolStore(): SpoolStore {
  const entries = new Map<string, Spooled>();
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
      return [...entries.values()].sort((a, b) => a.spooledAt - b.spooledAt);
    },
  };
}
