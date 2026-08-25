/**
 * The device token, in the platform keychain.
 *
 * Two options here are load-bearing and neither is a default:
 *
 * `keychainAccessible: WHEN_UNLOCKED_THIS_DEVICE_ONLY` keeps the token off iCloud Keychain
 * and out of encrypted backups. A device token identifies *this phone*; restoring it onto a
 * new one would silently give a second device a first device's identity, and revoking the
 * lost phone would then revoke the new one too.
 *
 * `accessGroup` is the App Group. Apple permits an app-group identifier to be used directly
 * as a keychain access group, which is what lets the share extension read the same token
 * without a second pairing. (The option is spelled `accessGroup` — not
 * `keychainAccessGroup`, which is what the equivalent React Native library calls it.)
 */

import * as SecureStore from "expo-secure-store";

import type { TokenStore } from "@anuvritti/client";

/** Must match `ios.entitlements` and the `expo-sharing` plugin's `appGroupId` in app.json. */
export const APP_GROUP = "group.com.anuvritti.app";

const KEY = "device-token";

const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainService: "anuvritti",
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  accessGroup: APP_GROUP,
};

export function secureTokenStore(): TokenStore {
  return {
    read: () => SecureStore.getItemAsync(KEY, OPTIONS),
    write: (token) => SecureStore.setItemAsync(KEY, token, OPTIONS),
    clear: () => SecureStore.deleteItemAsync(KEY, OPTIONS),
  };
}
