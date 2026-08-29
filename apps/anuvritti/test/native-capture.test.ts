import { describe, it } from "node:test";
import assert from "node:assert/strict";

import type { QueueStore, QueuedCapture } from "@anuvritti/client";
import {
  COLD_START_BUDGET_MS,
  NativeCaptureManager,
  type NativeMediaDriver,
} from "../src/capture/native.ts";
import { HardwareDeviceVault, type SecureKeyStorage } from "../src/vault/device-vault.ts";

function makeMockStorage(): SecureKeyStorage {
  const store = new Map<string, string>();
  return {
    getItem: async (key: string) => store.get(key) ?? null,
    setItem: async (key: string, value: string) => {
      store.set(key, value);
    },
    deleteItem: async (key: string) => {
      store.delete(key);
    },
  };
}

describe("TASK-1003 — In-App Native Capture (PRD 11, PRD 8.2)", () => {
  it("captures a photo moment and encrypts it to queue within the 10-second budget", async () => {
    const queueEntries: QueuedCapture[] = [];
    const mockQueue: QueueStore = {
      async append(entry) {
        queueEntries.push(entry);
      },
      async replace() {},
      async remove() {},
      async list() {
        return queueEntries;
      },
    };

    const vault = new HardwareDeviceVault(makeMockStorage());
    const manager = new NativeCaptureManager(mockQueue, vault);

    const mockDriver: NativeMediaDriver = {
      async takePhoto() {
        return {
          bytes: new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46]),
          mimeType: "image/jpeg",
          filename: "moment.jpg",
        };
      },
      async recordVoiceClip() {
        throw new Error("not used in this test");
      },
    };

    const result = await manager.capturePhotoMoment(mockDriver, {
      familyId: "fam-001",
      childId: "child-leo",
      title: "Leo learning to pedal tricycle",
    });

    assert.ok(result.queueId.startsWith("cap-photo-"));
    assert.equal(result.mediaType, "image/jpeg");
    assert.equal(result.encrypted, true);
    assert.ok(result.durationMs < COLD_START_BUDGET_MS);

    // Queue entry assertion
    assert.equal(queueEntries.length, 1);
    const entry = queueEntries[0]!;
    const body = entry.body as any;
    assert.equal(body.source_kind, "PHOTO");
    assert.equal(body.title, "Leo learning to pedal tricycle");
    assert.ok(body.encrypted_iv.length > 0);
    assert.ok(body.encrypted_payload.length > 0);
  });

  it("captures a voice spark directly into the encrypted spool", async () => {
    const queueEntries: QueuedCapture[] = [];
    const mockQueue: QueueStore = {
      async append(entry) {
        queueEntries.push(entry);
      },
      async replace() {},
      async remove() {},
      async list() {
        return queueEntries;
      },
    };

    const vault = new HardwareDeviceVault(makeMockStorage());
    const manager = new NativeCaptureManager(mockQueue, vault);

    const mockDriver: NativeMediaDriver = {
      async takePhoto() {
        throw new Error("not used");
      },
      async recordVoiceClip(durationMs) {
        return {
          bytes: new Uint8Array(durationMs / 10), // mock audio buffer
          mimeType: "audio/mp4",
          filename: "voice.m4a",
        };
      },
    };

    const result = await manager.captureVoiceSpark(mockDriver, {
      familyId: "fam-001",
      durationMs: 4500,
      note: "He said the moon follows our car",
    });

    assert.ok(result.queueId.startsWith("cap-voice-"));
    assert.equal(result.mediaType, "audio/mp4");
    assert.equal(result.encrypted, true);
    assert.ok(result.durationMs < COLD_START_BUDGET_MS);

    assert.equal(queueEntries.length, 1);
    const entry = queueEntries[0]!;
    const body = entry.body as any;
    assert.equal(body.source_kind, "VOICE");
    assert.equal(body.note, "He said the moon follows our car");
    assert.equal(body.duration_seconds, 5);
  });
});
