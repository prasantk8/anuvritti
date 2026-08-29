/**
 * The return arrives on the lock screen (TASK-1004, PRD 8.3, 8.5, 14).
 *
 * Local notifications scheduled on-device, at most one a day, silenceable forever in
 * one tap and never re-enabled by an update.
 *
 * Core guarantees:
 * 1. Zero server push: notifications are calculated and scheduled purely locally on-device.
 * 2. At most one a day: anti-metric (PRD 53) - the product never floods or nags a family.
 * 3. Permanent silence: when silenced, it stays silenced across cold boots and app upgrades.
 * 4. Zero guilt copy: no streaks, no number of days, no exclamation marks, no unread badges.
 */

import type { Suggestion } from "@anuvritti/client";

export interface NotificationPayload {
  readonly title: string;
  readonly body: string;
  readonly sparkId: string;
  readonly scheduledForTimestamp: number;
}

export interface NotificationPreferences {
  readonly silenced: boolean;
  readonly lastNotifiedDay?: string; // YYYY-MM-DD
}

export interface NotificationPreferencesStore {
  get(): Promise<NotificationPreferences>;
  set(prefs: NotificationPreferences): Promise<void>;
}

export interface LocalNotificationScheduler {
  schedule(notification: NotificationPayload): Promise<void>;
  cancelAll(): Promise<void>;
}

export interface NotificationSchedulerConfig {
  readonly store: NotificationPreferencesStore;
  readonly scheduler: LocalNotificationScheduler;
  readonly now: () => number;
}

/**
 * Format a gentle, guilt-free lock-screen notification.
 * No exclamation marks, no guilt, no streak counters.
 */
export function formatReturnNotification(
  suggestion: Suggestion,
  childName?: string
): { title: string; body: string } {
  const title = "Worth bringing back";
  const sparkTitle = suggestion.spark.title.trim();

  let body = "";
  if (childName && childName.trim()) {
    body = `Something you saved for ${childName.trim()}: ${sparkTitle}`;
  } else {
    body = `Something you saved a while ago: ${sparkTitle}`;
  }

  return { title, body };
}

/**
 * In-memory preference store for tests or environments without durable storage.
 */
export function memoryNotificationPreferencesStore(
  initial: NotificationPreferences = { silenced: false }
): NotificationPreferencesStore {
  let state = { ...initial };
  return {
    async get() {
      return { ...state };
    },
    async set(prefs) {
      state = { ...prefs };
    },
  };
}

export class ReturnNotificationManager {
  private store: NotificationPreferencesStore;
  private scheduler: LocalNotificationScheduler;
  private now: () => number;

  constructor(config: NotificationSchedulerConfig) {
    this.store = config.store;
    this.scheduler = config.scheduler;
    this.now = config.now;
  }

  /**
   * Silence lock-screen notifications permanently in one tap.
   */
  async silenceForever(): Promise<void> {
    await this.store.set({ silenced: true });
    await this.scheduler.cancelAll();
  }

  /**
   * Check if notifications are silenced.
   */
  async isSilenced(): Promise<boolean> {
    const prefs = await this.store.get();
    return prefs.silenced;
  }

  /**
   * Schedule at most one notification for today's eligible suggestion.
   * If already notified today or silenced, schedules nothing.
   */
  async scheduleIfEligible(
    suggestion: Suggestion | null,
    childName?: string,
    targetHour = 17 // 5:00 PM local
  ): Promise<NotificationPayload | null> {
    if (!suggestion) return null;

    const prefs = await this.store.get();
    if (prefs.silenced) {
      return null;
    }

    const currentDate = new Date(this.now());
    const todayStr = currentDate.toISOString().slice(0, 10);

    // At most one notification per calendar day
    if (prefs.lastNotifiedDay === todayStr) {
      return null;
    }

    const { title, body } = formatReturnNotification(suggestion, childName);

    // Schedule for target hour today, or immediate if past target
    const scheduledDate = new Date(currentDate);
    scheduledDate.setHours(targetHour, 0, 0, 0);

    let scheduledTime = scheduledDate.getTime();
    if (scheduledTime < this.now()) {
      // Past target hour; schedule for right now
      scheduledTime = this.now();
    }

    const payload: NotificationPayload = {
      title,
      body,
      sparkId: suggestion.spark.id,
      scheduledForTimestamp: scheduledTime,
    };

    await this.scheduler.schedule(payload);
    await this.store.set({
      silenced: false,
      lastNotifiedDay: todayStr,
    });

    return payload;
  }
}
