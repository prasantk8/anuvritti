import { describe, it } from "node:test";
import assert from "node:assert/strict";

import type {
  Elapsed,
  Instant,
  QueueStore,
  QueuedCapture,
  Suggestion,
} from "@anuvritti/client";
import { HardwareDeviceVault, type SecureKeyStorage } from "../src/vault/device-vault.ts";
import { NativeCaptureManager, type NativeMediaDriver } from "../src/capture/native.ts";
import {
  ResumableMediaUploader,
  type CheckpointStore,
  type ChunkUploadTransport,
  type UploadCheckpoint,
} from "../src/sync/uploader.ts";
import {
  ReturnNotificationManager,
  memoryNotificationPreferencesStore,
  type LocalNotificationScheduler,
  type NotificationPayload,
} from "../src/return/notifications.ts";

function makeMockStorage(): SecureKeyStorage {
  const store = new Map<string, string>();
  return {
    getItem: async (key) => store.get(key) ?? null,
    setItem: async (key, val) => {
      store.set(key, val);
    },
    deleteItem: async (key) => {
      store.delete(key);
    },
  };
}

describe("TASK-1010 — Mobile Subsystems End-to-End Integration (PRD 48)", () => {
  it("executes the full lifecycle: capture -> vault -> upload -> return -> lived", async () => {
    // 1. Storage & Vault setup
    const storage = makeMockStorage();
    const vault = new HardwareDeviceVault(storage);
    const queueEntries: QueuedCapture[] = [];
    const queue: QueueStore = {
      async append(entry) {
        queueEntries.push(entry);
      },
      async replace() {},
      async remove(id) {
        const idx = queueEntries.findIndex((e) => e.id === id);
        if (idx >= 0) queueEntries.splice(idx, 1);
      },
      async list() {
        return queueEntries;
      },
    };

    // 2. Real in-app capture
    const captureManager = new NativeCaptureManager(queue, vault);
    const mockDriver: NativeMediaDriver = {
      async takePhoto() {
        return {
          bytes: new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a]),
          mimeType: "image/png",
          filename: "first-drawing.png",
        };
      },
      async recordVoiceClip() {
        throw new Error("not used");
      },
    };

    const captureResult = await captureManager.capturePhotoMoment(mockDriver, {
      familyId: "fam-e2e",
      childId: "child-leo",
      title: "Leo drew a blue giraffe",
    });

    assert.ok(captureResult.queueId.startsWith("cap-photo-"));
    assert.equal(queueEntries.length, 1);

    // 3. Resumable Chunked Upload
    const checkpoints = new Map<string, UploadCheckpoint>();
    const checkpointStore: CheckpointStore = {
      async saveCheckpoint(cp) {
        checkpoints.set(cp.uploadId, cp);
      },
      async getCheckpoint(id) {
        return checkpoints.get(id) ?? null;
      },
      async clearCheckpoint(id) {
        checkpoints.delete(id);
      },
    };

    const transport: ChunkUploadTransport = {
      async uploadChunk({ offset, chunkData, totalBytes }) {
        const next = offset + chunkData.byteLength;
        const done = next >= totalBytes;
        return {
          receivedBytes: next,
          completed: done,
          mediaId: done ? "media-server-leo-giraffe" : undefined,
        };
      },
    };

    const uploader = new ResumableMediaUploader(checkpointStore, transport, 2);
    const mediaId = await uploader.upload({
      uploadId: captureResult.queueId,
      idempotencyKey: `idem-${captureResult.queueId}`,
      data: new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a]),
      mediaType: "image/png",
    });

    assert.equal(mediaId, "media-server-leo-giraffe");
    await queue.remove(captureResult.queueId);
    assert.equal(queueEntries.length, 0);

    // 4. Memory Return on Lock Screen Months Later
    const scheduledNotifications: NotificationPayload[] = [];
    const localScheduler: LocalNotificationScheduler = {
      async schedule(notification) {
        scheduledNotifications.push(notification);
      },
      async cancelAll() {
        scheduledNotifications.length = 0;
      },
    };

    const prefsStore = memoryNotificationPreferencesStore();
    const returnManager = new ReturnNotificationManager({
      store: prefsStore,
      scheduler: localScheduler,
      now: () => new Date("2026-08-29T17:00:00Z").getTime(),
    });

    const suggestion: Suggestion = {
      spark: {
        id: "spk-leo-giraffe",
        family_id: "fam-leo",
        owner_id: "mem-papa",
        title: "Leo drew a blue giraffe",
        source: { kind: "PHOTO", media_id: "med-giraffe" },
        intent: { value: "REMEMBER", source: "AI", confidence: 0.8, human_override: false },
        category: { value: "drawing", source: "AI", confidence: 0.6, human_override: false },
        tags: ["drawing"],
        status: "WAITING",
        visibility: "FAMILY",
        saved: "7 months ago" as Elapsed,
        created_at: "2026-01-15T10:00:00Z" as Instant,
      },
      reason: "Saved 7 months ago",
      elapsed: "7 months ago" as Elapsed,
      actions: ["maybe_later", "lets_do_it", "not_relevant_anymore"],
    };

    const notificationResult = await returnManager.scheduleIfEligible(suggestion, "Leo");
    assert.ok(notificationResult);
    assert.equal(scheduledNotifications.length, 1);
    assert.ok(scheduledNotifications[0]!.body.includes("Leo"));
    assert.ok(scheduledNotifications[0]!.body.includes("blue giraffe"));
  });
});
