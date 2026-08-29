/**
 * From a file on the phone to a recording in the archive (TASK-601, TASK-605, TASK-713).
 *
 * Three things happen, and the order is the whole design:
 *
 * 1. **The recording is taken into the app's own keeping and written down.** No network.
 *    `expo-audio` leaves its file in the cache directory, which iOS empties whenever it
 *    likes; the spool moves it into the document directory and records a row saying it
 *    exists and has not gone up yet. This is the only step a parent waits for, and it is
 *    a file move — well inside the ten seconds PRD §11 allows the whole of capture.
 * 2. **The bytes go up** — `POST /v1/media`, the slow one.
 * 3. **What they are goes up** — `POST /v1/voice`, small, and queued rather than awaited.
 *
 * ## What changed, and why it matters
 *
 * This used to upload synchronously and, when the upload failed, return a failure and leave
 * the file wherever the recorder had put it. The screen said "Still on your phone. It will
 * go up when there's signal", and nothing in the app was arranged to make the second half
 * of that sentence true: nothing remembered the file, and the directory it was in was the
 * one the OS reclaims first. A parent in a lift lost four seconds of their own voice and
 * was told they had not.
 *
 * Now the sentence is true. The failure this returns is `waiting`, not `lost` — the
 * recording is written down, and it goes up on the next drain, the next time the app comes
 * forward, or the next time the phone finds a network. See `src/upload/spool.ts` for how it
 * lands exactly once.
 */

import type { Outbox } from "../upload/spool.ts";

export interface Recorded {
  /** A `file://` uri from `expo-audio`. */
  readonly uri: string;
  readonly seconds: number;
  /** What the handset's own recogniser made of it, if anything. Always a machine reading. */
  readonly heard?: string;
  readonly heardConfidence?: number;
}

export interface KeepDeps {
  readonly outbox: Outbox;
}

export type Kept =
  | { readonly ok: true }
  /** Safe on the phone, not yet in the archive. Not a loss, and not a thing to redo. */
  | { readonly ok: false; readonly why: "waiting" }
  /** The server will not take these bytes, ever. The file is still on the phone. */
  | { readonly ok: false; readonly why: "refused" };

export async function keepRecording({ outbox }: KeepDeps, recorded: Recorded): Promise<Kept> {
  const entry = await outbox.spool(
    { uri: recorded.uri, mimeType: mimeFor(recorded.uri) },
    {
      kind: "voice",
      seconds: recorded.seconds,
      heard: recorded.heard,
      heardConfidence: recorded.heardConfidence,
    }
  );

  // Try immediately, because most of the time there is a network and a parent should see
  // their recording arrive on the shelf. Failing here is not a failure of the keep — the
  // recording is already written down and the spool owns it from now on.
  const report = await outbox.drain();
  if (report.refused.some(({ entry: refused }) => refused.id === entry.id)) {
    return { ok: false, why: "refused" };
  }

  const waiting = await outbox.pending();
  if (waiting.some((pending) => pending.id === entry.id)) return { ok: false, why: "waiting" };
  return { ok: true };
}

/**
 * The type the server is told, which is the type it has to accept.
 *
 * `.m4a` is an MPEG-4 container, so `audio/mp4` is the canonical answer and the one sent
 * here. The server also accepts `audio/x-m4a` and `audio/m4a`, because a share sheet
 * delivering someone else's voice memo will use one of those and refusing it would 415 a
 * real recording — the one failure on this path that loses a thing rather than delaying it.
 */
function mimeFor(uri: string): string {
  if (uri.endsWith(".3gp")) return "audio/3gpp";
  if (uri.endsWith(".webm")) return "audio/webm";
  if (uri.endsWith(".wav")) return "audio/wav";
  return "audio/mp4";
}
