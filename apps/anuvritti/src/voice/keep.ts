/**
 * From a file on the phone to a recording in the archive (TASK-601, TASK-605).
 *
 * Two requests, in this order, and the order is the whole design:
 *
 * 1. `POST /v1/media` — the bytes. The slow one, and it starts the instant the button is
 *    released, while the parent is still deciding whether to say anything about it.
 * 2. `POST /v1/voice` — what they are. Small, replayable, and queueable.
 *
 * A single multipart call would have to wait for both, which is the wrong trade against the
 * ten-second budget in PRD §11. It would also make the whole thing unqueueable: the offline
 * queue stores JSON in SQLite, and a file is not JSON.
 *
 * ## Which half survives losing the signal
 *
 * The upload cannot be queued, so when it fails the recording stays on the phone and this
 * returns a failure. That is honest, and it is the one path where "Saved." would be a lie.
 * Once the bytes are up, the small call is queued rather than awaited, so from that point
 * on nothing can lose it: a replayed `keepVoiceNote` carries its own idempotency key and
 * the server answers the second attempt with the first attempt's note.
 */

import type { CaptureQueue, Contract, Result } from "@anuvritti/client";

export interface Recorded {
  /** A `file://` uri from `expo-audio`. */
  readonly uri: string;
  readonly seconds: number;
  /** What the handset's own recogniser made of it, if anything. Always a machine reading. */
  readonly heard?: string;
  readonly heardConfidence?: number;
}

export interface KeepDeps {
  readonly api: Contract;
  readonly queue: CaptureQueue;
}

export type Kept =
  | { readonly ok: true; readonly mediaId: string }
  | { readonly ok: false; readonly why: "upload" };

/**
 * Upload the audio, then queue the note.
 *
 * `FormData` with a `{ uri, name, type }` part is React Native's own extension: the runtime
 * streams the file off disk rather than reading it into JavaScript. Passing a `Blob` here
 * instead would load a whole recording into memory on a device that has just been holding
 * a microphone open, and Hermes has no `File` at all.
 */
export async function keepRecording(
  { api, queue }: KeepDeps,
  recorded: Recorded
): Promise<Kept> {
  const form = new FormData();
  form.append("file", {
    uri: recorded.uri,
    name: nameFor(recorded.uri),
    type: mimeFor(recorded.uri),
  } as unknown as Blob);

  const uploaded: Result<{ id: string }> = await api.uploadMedia(form);
  if (!uploaded.ok) return { ok: false, why: "upload" };

  await queue.enqueue("keepVoiceNote", {
    media_id: uploaded.value.id,
    duration_seconds: recorded.seconds,
    heard_text: recorded.heard,
    heard_confidence: recorded.heardConfidence,
  });

  return { ok: true, mediaId: uploaded.value.id };
}

function nameFor(uri: string): string {
  const last = uri.split("/").pop();
  return last && last.includes(".") ? last : "recording.m4a";
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
