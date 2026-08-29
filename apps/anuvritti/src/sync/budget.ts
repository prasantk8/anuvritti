/**
 * Battery, Heat and Storage Budget (PRD 8.2, PRD 46).
 *
 * Rules:
 * 1. Capture never wakes the cellular radio: saving a memory is purely a local disk write.
 * 2. Background sync is strictly bounded: max 30s per execution window.
 * 3. Network uploads are batched on unmetered WiFi or while charging.
 * 4. The offline spool has an explicit ceiling and warns the parent at 80% and 95% capacity.
 */

export interface NetworkState {
  isConnected: boolean;
  isInternetReachable: boolean;
  isWifi: boolean;
  isCellular: boolean;
}

export interface PowerState {
  batteryLevel: number; // 0.0 to 1.0
  isCharging: boolean;
  isLowPowerMode: boolean;
}

export interface SpoolStorageStatus {
  usedBytes: number;
  maxBytes: number;
  itemCount: number;
  maxItems: number;
  percentageUsed: number;
  warningLevel: "ok" | "warning_80" | "critical_95" | "full_100";
}

export const MAX_SPOOL_BYTES = 500 * 1024 * 1024; // 500 MB maximum offline queue
export const MAX_SPOOL_ITEMS = 1000;
export const MAX_BACKGROUND_SYNC_MS = 30000; // 30 seconds hard execution cap

export class DeviceResourceBudget {
  private _maxSpoolBytes: number;
  private _maxSpoolItems: number;

  constructor(
    maxSpoolBytes: number = MAX_SPOOL_BYTES,
    maxSpoolItems: number = MAX_SPOOL_ITEMS
  ) {
    this._maxSpoolBytes = maxSpoolBytes;
    this._maxSpoolItems = maxSpoolItems;
  }

  /**
   * Evaluates whether the sync engine should wake the radio.
   * Pure capture events NEVER wake the radio immediately.
   */
  shouldWakeRadio(params: {
    network: NetworkState;
    power: PowerState;
    queuedCount: number;
    userInitiated?: boolean;
    urgent?: boolean;
  }): boolean {
    if (!params.network.isConnected || !params.network.isInternetReachable) {
      return false;
    }

    // User explicitly triggered refresh or sync
    if (params.userInitiated) {
      return true;
    }

    // Low power mode strictly disables automatic radio wakes
    if (params.power.isLowPowerMode && params.power.batteryLevel < 0.20 && !params.power.isCharging) {
      return false;
    }

    // Unmetered WiFi or active charging allows normal background queue draining
    if (params.network.isWifi || params.power.isCharging) {
      return params.queuedCount > 0;
    }

    // On cellular battery: batch until queue accumulates or power is connected
    return params.queuedCount >= 5;
  }

  /**
   * Asserts and evaluates current spool storage pressure.
   */
  evaluateSpoolStorage(usedBytes: number, itemCount: number): SpoolStorageStatus {
    const bytesRatio = usedBytes / this._maxSpoolBytes;
    const itemsRatio = itemCount / this._maxSpoolItems;
    const percentageUsed = Math.min(100, Math.round(Math.max(bytesRatio, itemsRatio) * 100));

    let warningLevel: SpoolStorageStatus["warningLevel"] = "ok";
    if (percentageUsed >= 100) {
      warningLevel = "full_100";
    } else if (percentageUsed >= 95) {
      warningLevel = "critical_95";
    } else if (percentageUsed >= 80) {
      warningLevel = "warning_80";
    }

    return {
      usedBytes,
      maxBytes: this._maxSpoolBytes,
      itemCount,
      maxItems: this._maxSpoolItems,
      percentageUsed,
      warningLevel,
    };
  }

  /**
   * Generates gentle, guilt-free storage warning copy for the parent.
   */
  formatStorageNotice(status: SpoolStorageStatus): string | null {
    if (status.warningLevel === "warning_80") {
      return "Your offline queue is holding many memories. Connect to Wi-Fi to sync them safely.";
    }
    if (status.warningLevel === "critical_95" || status.warningLevel === "full_100") {
      return "Your offline storage is nearly full. Please connect to Wi-Fi so your memories can reach your archive.";
    }
    return null;
  }
}
