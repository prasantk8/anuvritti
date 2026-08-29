import { describe, it } from "node:test";
import assert from "node:assert/strict";

import type { QueueStore, QueuedCapture } from "@anuvritti/client";
import {
  HardwareDeviceVault,
  encryptedQueueStore,
  type SecureKeyStorage,
} from "../src/vault/device-vault.ts";

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

describe("TASK-1001 — The Device Vault (PRD 21, PRD 44, HARDENING 5.1)", () => {
  it("encrypts and decrypts strings with hardware-backed AES-GCM", async () => {
    const storage = makeMockStorage();
    const vault = new HardwareDeviceVault(storage);
    const secret = "A child's voice note from 3am in the hospital";

    const ciphertext = await vault.encrypt(secret);
    assert.notEqual(ciphertext, secret);
    assert.equal(ciphertext.includes(secret), false);

    const decrypted = await vault.decrypt(ciphertext);
    assert.equal(decrypted, secret);
  });

  it("encrypts and decrypts binary media payloads", async () => {
    const storage = makeMockStorage();
    const vault = new HardwareDeviceVault(storage);
    const mediaBytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x42]);

    const { iv, ciphertext } = await vault.encryptBinary(mediaBytes);
    assert.ok(iv.length > 0);
    assert.ok(ciphertext.length > 0);

    const restoredBytes = await vault.decryptBinary(iv, ciphertext);
    assert.deepEqual(restoredBytes, mediaBytes);
  });

  it("fails decryption when ciphertext is tampered with", async () => {
    const storage = makeMockStorage();
    const vault = new HardwareDeviceVault(storage);
    const secret = "Original sensitive payload";
    const ciphertext = await vault.encrypt(secret);
    const [iv, rawCipher] = ciphertext.split(":");

    // Tamper with ciphertext by corrupting last character
    const tampered = `${iv}:${rawCipher!.slice(0, -2)}AA`;
    await assert.rejects(async () => {
      await vault.decrypt(tampered);
    });
  });

  it("decorates an offline QueueStore with seamless at-rest encryption", async () => {
    const rawStorage: QueuedCapture[] = [];
    const memoryQueueStore: QueueStore = {
      async append(entry: QueuedCapture) {
        rawStorage.push(entry);
      },
      async replace(entry: QueuedCapture) {
        const idx = rawStorage.findIndex((e) => e.id === entry.id);
        if (idx >= 0) rawStorage[idx] = entry;
      },
      async remove(id: string) {
        const idx = rawStorage.findIndex((e) => e.id === id);
        if (idx >= 0) rawStorage.splice(idx, 1);
      },
      async list() {
        return [...rawStorage];
      },
    };

    const storage = makeMockStorage();
    const vault = new HardwareDeviceVault(storage);
    const secureQueue = encryptedQueueStore(memoryQueueStore, vault);

    const sensitiveEntry: QueuedCapture = {
      id: "cap-001",
      operation: "captureSpark",
      pathArgs: ["fam-123"],
      body: {
        title: "First steps across the living room",
        note: "He held onto the coffee table then let go",
      },
      enqueuedAt: Date.now(),
      attempts: 0,
      nextAttemptAt: Date.now(),
    };

    await secureQueue.append(sensitiveEntry);

    // Assert underlying storage holds NO PLAINTEXT strings
    assert.equal(rawStorage.length, 1);
    const storedRow = rawStorage[0]!;
    assert.equal(typeof storedRow.body, "string");
    assert.equal((storedRow.body as string).includes("First steps"), false);
    assert.equal((storedRow.body as string).includes("living room"), false);
    assert.equal((storedRow.body as string).includes("coffee table"), false);

    // Reading back through encryptedQueueStore transparently decrypts
    const queuedItems = await secureQueue.list();
    assert.equal(queuedItems.length, 1);
    assert.deepEqual(queuedItems[0]!.body, sensitiveEntry.body);
    assert.deepEqual(queuedItems[0]!.pathArgs, sensitiveEntry.pathArgs);
  });

  it("purge wipes vault key, preventing prior ciphertexts from being decrypted", async () => {
    const storage = makeMockStorage();
    const vault = new HardwareDeviceVault(storage);
    const secret = "Secret to be rendered unreadable upon purge";

    const ciphertext = await vault.encrypt(secret);
    await vault.purge();

    // New vault instance with purged storage will generate a new key and fail to decrypt old ciphertext
    const newVault = new HardwareDeviceVault(storage);
    await assert.rejects(async () => {
      await newVault.decrypt(ciphertext);
    });
  });
});
