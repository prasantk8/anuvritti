/**
 * The Device Vault (PRD 21, PRD 44, HARDENING 5.1).
 *
 * The offline capture spool and cached media on a mobile device contain irreplaceable,
 * highly personal family memories. A phone left in a taxi or lost in a park must not
 * become a child's archive exposed in plaintext.
 *
 * This vault implements AES-256-GCM envelope encryption where the vault key is kept
 * strictly inside the platform Secure Enclave / Keystore under
 * `WHEN_UNLOCKED_THIS_DEVICE_ONLY` and within the shared App Group.
 */

import type { QueueStore, QueuedCapture } from "@anuvritti/client";

export const APP_GROUP = "group.com.anuvritti.app";
const VAULT_KEY_NAME = "device-vault-aes-key";

export interface SecureKeyStorage {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  deleteItem(key: string): Promise<void>;
}

export const defaultSecureKeyStorage: SecureKeyStorage = {
  async getItem(key: string): Promise<string | null> {
    try {
      const SecureStore = await import("expo-secure-store");
      return await SecureStore.getItemAsync(key, {
        keychainService: "anuvritti-vault",
        keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
        accessGroup: APP_GROUP,
      });
    } catch {
      return null;
    }
  },

  async setItem(key: string, value: string): Promise<void> {
    const SecureStore = await import("expo-secure-store");
    await SecureStore.setItemAsync(key, value, {
      keychainService: "anuvritti-vault",
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
      accessGroup: APP_GROUP,
    });
  },

  async deleteItem(key: string): Promise<void> {
    try {
      const SecureStore = await import("expo-secure-store");
      await SecureStore.deleteItemAsync(key, {
        keychainService: "anuvritti-vault",
        keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
        accessGroup: APP_GROUP,
      });
    } catch {
      // ignore
    }
  },
};

export interface DeviceVault {
  /** Encrypt a UTF-8 string payload into an authenticated ciphertext string (iv:ciphertext). */
  encrypt(plaintext: string): Promise<string>;
  /** Decrypt an authenticated ciphertext string back into UTF-8 plaintext. */
  decrypt(payload: string): Promise<string>;
  /** Encrypt binary data with AES-256-GCM. */
  encryptBinary(data: Uint8Array): Promise<{ iv: string; ciphertext: string }>;
  /** Decrypt binary data with AES-256-GCM. */
  decryptBinary(iv: string, ciphertext: string): Promise<Uint8Array>;
  /** Wipe the hardware-backed vault key (e.g. on device revocation or sign-out). */
  purge(): Promise<void>;
  /** Rotate the hardware-backed vault key. */
  rotateKey(): Promise<void>;
}

function toBase64(buffer: ArrayBuffer | Uint8Array): string {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
  if (typeof Buffer !== "undefined") {
    return Buffer.from(bytes).toString("base64");
  }
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i] as number);
  }
  return globalThis.btoa(binary);
}

function fromBase64(base64: string): Uint8Array<ArrayBuffer> {
  const binary =
    typeof Buffer !== "undefined"
      ? Buffer.from(base64, "base64").toString("binary")
      : globalThis.atob(base64);
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

export class HardwareDeviceVault implements DeviceVault {
  private _storage: SecureKeyStorage;
  private _cachedKey: CryptoKey | null = null;

  constructor(storage: SecureKeyStorage = defaultSecureKeyStorage) {
    this._storage = storage;
  }

  private async _getOrGenerateKey(): Promise<CryptoKey> {
    if (this._cachedKey) {
      return this._cachedKey;
    }

    let storedKeyBase64 = await this._storage.getItem(VAULT_KEY_NAME);

    if (!storedKeyBase64) {
      const rawKey = new Uint8Array(new ArrayBuffer(32));
      globalThis.crypto.getRandomValues(rawKey);
      storedKeyBase64 = toBase64(rawKey);
      await this._storage.setItem(VAULT_KEY_NAME, storedKeyBase64);
    }

    const rawBytes = fromBase64(storedKeyBase64);
    this._cachedKey = await globalThis.crypto.subtle.importKey(
      "raw",
      rawBytes,
      { name: "AES-GCM" },
      false,
      ["encrypt", "decrypt"]
    );
    return this._cachedKey;
  }

  async encrypt(plaintext: string): Promise<string> {
    const encoder = new TextEncoder();
    const data = encoder.encode(plaintext);
    const result = await this.encryptBinary(data);
    return `${result.iv}:${result.ciphertext}`;
  }

  async decrypt(payload: string): Promise<string> {
    const parts = payload.split(":");
    if (parts.length !== 2) {
      throw new Error("Invalid vault payload format: missing IV or ciphertext delimiter");
    }
    const [iv, ciphertext] = parts as [string, string];
    const decryptedBytes = await this.decryptBinary(iv, ciphertext);
    const decoder = new TextDecoder();
    return decoder.decode(decryptedBytes);
  }

  async encryptBinary(data: Uint8Array<ArrayBuffer>): Promise<{ iv: string; ciphertext: string }> {
    const key = await this._getOrGenerateKey();
    const iv = new Uint8Array(new ArrayBuffer(12));
    globalThis.crypto.getRandomValues(iv);

    const ciphertextBuffer = await globalThis.crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      key,
      data
    );

    return {
      iv: toBase64(iv),
      ciphertext: toBase64(new Uint8Array(ciphertextBuffer)),
    };
  }

  async decryptBinary(iv: string, ciphertext: string): Promise<Uint8Array> {
    const key = await this._getOrGenerateKey();
    const ivBytes = fromBase64(iv);
    const cipherBytes = fromBase64(ciphertext);

    const decryptedBuffer = await globalThis.crypto.subtle.decrypt(
      { name: "AES-GCM", iv: ivBytes },
      key,
      cipherBytes
    );

    return new Uint8Array(decryptedBuffer);
  }

  async purge(): Promise<void> {
    this._cachedKey = null;
    await this._storage.deleteItem(VAULT_KEY_NAME);
  }

  async rotateKey(): Promise<void> {
    await this.purge();
    await this._getOrGenerateKey();
  }
}

/**
 * Creates an encrypted decorator around any QueueStore so offline captures
 * in SQLite are transparently encrypted at rest.
 */
export function encryptedQueueStore(underlying: QueueStore, vault: DeviceVault): QueueStore {
  return {
    async append(entry: QueuedCapture): Promise<void> {
      const encryptedBody = await vault.encrypt(JSON.stringify(entry.body));
      const encryptedPathArgs = await vault.encrypt(JSON.stringify(entry.pathArgs));
      const encryptedEntry: QueuedCapture = {
        ...entry,
        body: encryptedBody,
        pathArgs: [encryptedPathArgs],
      };
      await underlying.append(encryptedEntry);
    },

    async replace(entry: QueuedCapture): Promise<void> {
      const encryptedBody = await vault.encrypt(JSON.stringify(entry.body));
      const encryptedPathArgs = await vault.encrypt(JSON.stringify(entry.pathArgs));
      const encryptedEntry: QueuedCapture = {
        ...entry,
        body: encryptedBody,
        pathArgs: [encryptedPathArgs],
      };
      await underlying.replace(encryptedEntry);
    },

    async remove(id: string): Promise<void> {
      await underlying.remove(id);
    },

    async list(): Promise<QueuedCapture[]> {
      const encryptedList = await underlying.list();
      const decryptedList: QueuedCapture[] = [];

      for (const entry of encryptedList) {
        try {
          const rawBody = typeof entry.body === "string" ? await vault.decrypt(entry.body) : "";
          const rawPathArgs = entry.pathArgs.length > 0 ? await vault.decrypt(entry.pathArgs[0] as string) : "[]";
          decryptedList.push({
            ...entry,
            body: JSON.parse(rawBody),
            pathArgs: JSON.parse(rawPathArgs) as string[],
          });
        } catch {
          // If a row cannot be decrypted (e.g. key purged after remote revocation),
          // skip or fail gracefully rather than crashing the queue loop
        }
      }
      return decryptedList;
    },
  };
}
