/**
 * In-App Native Camera & Microphone Capture (PRD 11, PRD 8.2).
 *
 * Capturing a moment happening in front of a parent cannot afford camera launch delays
 * or leaving for another app. Cold start to encrypted local save must complete in under
 * 10 seconds.
 */

import type { QueueStore, QueuedCapture } from "@anuvritti/client";
import type { DeviceVault } from "../vault/device-vault.ts";

export interface NativeMediaDriver {
  takePhoto(): Promise<{ bytes: Uint8Array; mimeType: string; filename: string }>;
  recordVoiceClip(durationMs: number): Promise<{ bytes: Uint8Array; mimeType: string; filename: string }>;
}

export interface CaptureResult {
  queueId: string;
  mediaType: string;
  totalBytes: number;
  durationMs: number;
  encrypted: boolean;
}

export const COLD_START_BUDGET_MS = 10000; // 10 seconds ceiling (PRD 11)

export class NativeCaptureManager {
  private _queue: QueueStore;
  private _vault: DeviceVault;

  constructor(queue: QueueStore, vault: DeviceVault) {
    this._queue = queue;
    this._vault = vault;
  }

  async capturePhotoMoment(
    driver: NativeMediaDriver,
    params: {
      familyId: string;
      childId?: string;
      title?: string;
      reflection?: string;
    }
  ): Promise<CaptureResult> {
    const startTime = Date.now();

    // 1. Capture media via native driver
    const media = await driver.takePhoto();

    // 2. Encrypt media payload
    const encryptedMedia = await this._vault.encryptBinary(media.bytes);

    // 3. Spool to local capture queue
    const queueId = `cap-photo-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const queueEntry: QueuedCapture = {
      id: queueId,
      operation: "captureSpark",
      pathArgs: [params.familyId],
      body: {
        source_kind: "PHOTO",
        mime_type: media.mimeType,
        encrypted_iv: encryptedMedia.iv,
        encrypted_payload: encryptedMedia.ciphertext,
        subject_child_id: params.childId,
        title: params.title || "Photo moment",
        reflection: params.reflection,
        captured_at: new Date().toISOString(),
      },
      enqueuedAt: Date.now(),
      attempts: 0,
      nextAttemptAt: Date.now(),
    };

    await this._queue.append(queueEntry);

    const durationMs = Date.now() - startTime;
    if (durationMs > COLD_START_BUDGET_MS) {
      // Log budget alert but do not discard saved capture
    }

    return {
      queueId,
      mediaType: media.mimeType,
      totalBytes: media.bytes.byteLength,
      durationMs,
      encrypted: true,
    };
  }

  async captureVoiceSpark(
    driver: NativeMediaDriver,
    params: {
      familyId: string;
      durationMs: number;
      childId?: string;
      note?: string;
    }
  ): Promise<CaptureResult> {
    const startTime = Date.now();

    const media = await driver.recordVoiceClip(params.durationMs);
    const encryptedMedia = await this._vault.encryptBinary(media.bytes);

    const queueId = `cap-voice-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const queueEntry: QueuedCapture = {
      id: queueId,
      operation: "captureSpark",
      pathArgs: [params.familyId],
      body: {
        source_kind: "VOICE",
        mime_type: media.mimeType,
        encrypted_iv: encryptedMedia.iv,
        encrypted_payload: encryptedMedia.ciphertext,
        subject_child_id: params.childId,
        note: params.note,
        duration_seconds: Math.round(params.durationMs / 1000),
        captured_at: new Date().toISOString(),
      },
      enqueuedAt: Date.now(),
      attempts: 0,
      nextAttemptAt: Date.now(),
    };

    await this._queue.append(queueEntry);
    const durationMs = Date.now() - startTime;

    return {
      queueId,
      mediaType: media.mimeType,
      totalBytes: media.bytes.byteLength,
      durationMs,
      encrypted: true,
    };
  }
}
