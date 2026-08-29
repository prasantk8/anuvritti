/** The resumable first-run marker, kept on this device and nowhere else. */

import * as SecureStore from "expo-secure-store";

import type { ThresholdMarker } from "../model/threshold.ts";

const KEY = "first-run-threshold";
const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainService: "anuvritti-threshold",
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

export async function readThreshold(): Promise<ThresholdMarker | null> {
  const held = await SecureStore.getItemAsync(KEY, OPTIONS);
  if (!held) return null;
  try {
    const value: unknown = JSON.parse(held);
    if (
      typeof value === "object" &&
      value !== null &&
      "familyId" in value &&
      typeof value.familyId === "string"
    ) {
      const childName =
        "childName" in value && typeof value.childName === "string" ? value.childName : undefined;
      return { familyId: value.familyId, childName };
    }
  } catch {
    // A corrupt marker must not hold a paired family outside its archive forever.
  }
  await SecureStore.deleteItemAsync(KEY, OPTIONS);
  return null;
}

export function writeThreshold(marker: ThresholdMarker): Promise<void> {
  return SecureStore.setItemAsync(KEY, JSON.stringify(marker), OPTIONS);
}

export function clearThreshold(): Promise<void> {
  return SecureStore.deleteItemAsync(KEY, OPTIONS);
}

