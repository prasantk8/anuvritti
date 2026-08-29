import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  DeviceResourceBudget,
  MAX_BACKGROUND_SYNC_MS,
  MAX_SPOOL_BYTES,
  type NetworkState,
  type PowerState,
} from "../src/sync/budget.ts";

describe("TASK-1008 — Battery, Heat & Storage Budget (PRD 8.2, PRD 46)", () => {
  const wifiNetwork: NetworkState = {
    isConnected: true,
    isInternetReachable: true,
    isWifi: true,
    isCellular: false,
  };

  const cellularNetwork: NetworkState = {
    isConnected: true,
    isInternetReachable: true,
    isWifi: false,
    isCellular: true,
  };

  const normalBattery: PowerState = {
    batteryLevel: 0.75,
    isCharging: false,
    isLowPowerMode: false,
  };

  const lowPowerMode: PowerState = {
    batteryLevel: 0.15,
    isCharging: false,
    isLowPowerMode: true,
  };

  it("suppresses radio wake on cellular battery for single captures", () => {
    const budget = new DeviceResourceBudget();
    // A single capture on cellular battery does NOT wake radio
    const wake = budget.shouldWakeRadio({
      network: cellularNetwork,
      power: normalBattery,
      queuedCount: 1,
    });
    assert.equal(wake, false);
  });

  it("wakes radio immediately when connected to Wi-Fi or charging", () => {
    const budget = new DeviceResourceBudget();

    // On Wi-Fi, 1 item wakes sync
    assert.equal(
      budget.shouldWakeRadio({
        network: wifiNetwork,
        power: normalBattery,
        queuedCount: 1,
      }),
      true
    );

    // On cellular but charging, 1 item wakes sync
    assert.equal(
      budget.shouldWakeRadio({
        network: cellularNetwork,
        power: { ...normalBattery, isCharging: true },
        queuedCount: 1,
      }),
      true
    );
  });

  it("permits user-initiated pull-to-refresh regardless of network type", () => {
    const budget = new DeviceResourceBudget();
    assert.equal(
      budget.shouldWakeRadio({
        network: cellularNetwork,
        power: lowPowerMode,
        queuedCount: 1,
        userInitiated: true,
      }),
      true
    );
  });

  it("warns parent when offline spool reaches 80% and 95% capacity", () => {
    const budget = new DeviceResourceBudget(1000, 100); // 1000 bytes max

    const safe = budget.evaluateSpoolStorage(500, 50);
    assert.equal(safe.warningLevel, "ok");
    assert.equal(budget.formatStorageNotice(safe), null);

    const warn80 = budget.evaluateSpoolStorage(820, 50);
    assert.equal(warn80.warningLevel, "warning_80");
    const notice80 = budget.formatStorageNotice(warn80);
    assert.ok(notice80?.includes("Wi-Fi"));
    assert.equal(notice80?.includes("!"), false);

    const crit95 = budget.evaluateSpoolStorage(960, 50);
    assert.equal(crit95.warningLevel, "critical_95");
    const notice95 = budget.formatStorageNotice(crit95);
    assert.ok(notice95?.includes("nearly full"));
    assert.equal(notice95?.includes("!"), false);
  });

  it("enforces background sync hard execution duration cap of 30 seconds", () => {
    assert.equal(MAX_BACKGROUND_SYNC_MS, 30000);
  });
});
