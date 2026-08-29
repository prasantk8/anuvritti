/**
 * TASK-1004 — The return arrives on the lock screen (PRD 8.3, 8.5, 14).
 *
 * Unit tests verifying:
 * 1. At most one notification per calendar day.
 * 2. Silenceable forever in one tap.
 * 3. An app update or restart never re-enables silenced notifications.
 * 4. Zero guilt, zero exclamation marks, zero streak counters.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { Elapsed, Instant, Suggestion } from "@anuvritti/client";

import type {
  LocalNotificationScheduler,
  NotificationPayload,
} from "../src/return/notifications.ts";
import {
  ReturnNotificationManager,
  formatReturnNotification,
  memoryNotificationPreferencesStore,
} from "../src/return/notifications.ts";

function fakeSuggestion(overrides: Partial<Suggestion> = {}): Suggestion {
  return {
    spark: {
      id: "spk-001",
      family_id: "fam-001",
      owner_id: "mem-001",
      title: "Build a cardboard rocket",
      source: { kind: "URL", url: "https://example.com/rocket" },
      intent: { value: "DO", source: "HUMAN", confidence: 1.0, human_override: true },
      category: { value: "crafts", source: "DEFAULT", confidence: 0.0, human_override: false },
      tags: ["crafts"],
      status: "WAITING",
      visibility: "FAMILY",
      saved: "8 months ago" as Elapsed,
      created_at: "2024-05-10T10:00:00Z" as Instant,
    },
    reason: "Saved 8 months ago",
    elapsed: "8 months ago" as Elapsed,
    actions: ["maybe_later", "lets_do_it", "not_relevant_anymore"],
    ...overrides,
  };
}

class FakeLocalScheduler implements LocalNotificationScheduler {
  public scheduled: NotificationPayload[] = [];
  public cancelledAll = false;

  async schedule(notification: NotificationPayload): Promise<void> {
    this.scheduled.push(notification);
  }

  async cancelAll(): Promise<void> {
    this.cancelledAll = true;
    this.scheduled = [];
  }
}

describe("TASK-1004 — Lock-screen Return Notifications", () => {
  it("formats notification copy with warmth, context, and zero guilt", () => {
    const suggestion = fakeSuggestion();
    const formatted = formatReturnNotification(suggestion, "Leo");

    assert.equal(formatted.title, "Worth bringing back");
    assert.equal(
      formatted.body,
      "Something you saved for Leo: Build a cardboard rocket"
    );

    // Ethical copy rules: no exclamation mark, no streak, no guilt
    assert.doesNotMatch(formatted.body, /!/);
    assert.doesNotMatch(formatted.body, /streak|hurry|miss|catch up|days ago/i);
  });

  it("schedules at most one notification per calendar day", async () => {
    const store = memoryNotificationPreferencesStore();
    const scheduler = new FakeLocalScheduler();
    let currentTimestamp = new Date("2026-08-29T10:00:00Z").getTime();
    const now = () => currentTimestamp;

    const manager = new ReturnNotificationManager({ store, scheduler, now });

    // First attempt today -> scheduled
    const first = await manager.scheduleIfEligible(fakeSuggestion(), "Leo");
    assert.ok(first);
    assert.equal(scheduler.scheduled.length, 1);
    assert.equal(first?.sparkId, "spk-001");

    // Second attempt on the same day -> skipped
    const second = await manager.scheduleIfEligible(fakeSuggestion(), "Leo");
    assert.equal(second, null);
    assert.equal(scheduler.scheduled.length, 1); // Still exactly 1

    // Advance to next day -> allowed again
    currentTimestamp += 24 * 60 * 60 * 1000;
    const third = await manager.scheduleIfEligible(fakeSuggestion(), "Leo");
    assert.ok(third);
    assert.equal(scheduler.scheduled.length, 2);
  });

  it("silences notifications forever in one single tap and clears queued alerts", async () => {
    const store = memoryNotificationPreferencesStore();
    const scheduler = new FakeLocalScheduler();
    const currentTimestamp = new Date("2026-08-29T10:00:00Z").getTime();
    const now = () => currentTimestamp;

    const manager = new ReturnNotificationManager({ store, scheduler, now });

    await manager.silenceForever();

    assert.equal(await manager.isSilenced(), true);
    assert.equal(scheduler.cancelledAll, true);

    // Attempting to schedule while silenced returns null
    const res = await manager.scheduleIfEligible(fakeSuggestion(), "Leo");
    assert.equal(res, null);
    assert.equal(scheduler.scheduled.length, 0);
  });

  it("an app update or restart never re-enables silenced notifications", async () => {
    // Durable store retains silenced state
    const sharedStore = memoryNotificationPreferencesStore({ silenced: true });
    const scheduler = new FakeLocalScheduler();
    const now = () => new Date("2026-09-01T12:00:00Z").getTime();

    // App boots afresh with the existing store
    const restartedManager = new ReturnNotificationManager({
      store: sharedStore,
      scheduler,
      now,
    });

    assert.equal(await restartedManager.isSilenced(), true);

    const result = await restartedManager.scheduleIfEligible(fakeSuggestion(), "Leo");
    assert.equal(result, null);
    assert.equal(scheduler.scheduled.length, 0);
  });
});
