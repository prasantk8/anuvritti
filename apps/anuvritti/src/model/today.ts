/**
 * Papa Today (TASK-807, PRD 16, PRD 8.4, PRD 8.5).
 *
 * The home screen occasionally taps you on the shoulder:
 * - 'Leave him a twenty-second message.'
 * - 'Put the phone down and go sit with her.'
 * - 'You once saved something about the moon. Look outside tonight.'
 *
 * Rules:
 * 1. At most one line a day.
 * 2. Drawn from the family's archive or ambient presence.
 * 3. Sometimes telling the parent to close the app.
 * 4. Never counted, never streaked.
 * 5. Silence (null) for weeks/months is a valid, normal output.
 */

import type { Spark } from "@anuvritti/client";

export interface TodayThought {
  readonly text: string;
  readonly kind: "voice" | "presence" | "spark_recall" | "close_app";
  readonly sparkId?: string;
}

export interface TodayContext {
  readonly dayOrdinal: number; // e.g. Math.floor(Date.now() / 86400000)
  readonly childName?: string;
  readonly childPronoun?: "he" | "she" | "they";
  readonly recentSparks?: readonly Spark[];
  readonly lastVoiceNoteDaysAgo?: number;
}

const AMBIENT_PROMPTS = [
  (name: string, p: string, obj: string) => `Leave ${obj} a twenty-second message.`,
  (name: string, p: string, obj: string) => `Put the phone down and go sit with ${obj}.`,
  (name: string, p: string, obj: string) => `Ask ${obj} what made ${obj === "them" ? "them" : obj} laugh today.`,
  (name: string, p: string, obj: string) => `Look outside together tonight.`,
  (name: string, p: string, obj: string) => `Notice what ${p} is humming today.`,
  (name: string, p: string, obj: string) => `Go play outside for ten minutes.`,
] as const;

function pronouns(p: "he" | "she" | "they" = "he"): { subj: string; obj: string; pos: string } {
  if (p === "she") return { subj: "she", obj: "her", pos: "her" };
  if (p === "they") return { subj: "they", obj: "them", pos: "their" };
  return { subj: "he", obj: "him", pos: "his" };
}

/**
 * Deterministically select a gentle prompt for today, or silence.
 * Silence is normal: on many days (or when unprompted), it returns null.
 */
export function papaToday(ctx: TodayContext): TodayThought | null {
  const child = ctx.childName?.trim() || "him";
  const { subj, obj } = pronouns(ctx.childPronoun);

  // 1. If there's an interesting old spark matching today's hash, recall it gently
  if (ctx.recentSparks && ctx.recentSparks.length > 0) {
    const sparkIndex = ctx.dayOrdinal % (ctx.recentSparks.length * 3); // 1 in 3 chance of spark recall
    if (sparkIndex < ctx.recentSparks.length) {
      const spark = ctx.recentSparks[sparkIndex];
      if (spark && spark.title) {
        return {
          text: `You once saved something about ${spark.title.toLowerCase()}. Look outside tonight.`,
          kind: "spark_recall",
          sparkId: spark.id,
        };
      }
    }
  }

  // 2. Ambient prompts (rotated deterministically by day)
  const promptIdx = ctx.dayOrdinal % (AMBIENT_PROMPTS.length * 2);
  if (promptIdx < AMBIENT_PROMPTS.length) {
    const generator = AMBIENT_PROMPTS[promptIdx];
    if (generator) {
      const text = generator(child, subj, obj);
      let kind: TodayThought["kind"] = "presence";
      if (text.includes("message")) kind = "voice";
      if (text.includes("Put the phone down")) kind = "close_app";

      return { text, kind };
    }
  }

  // 3. Silence is a valid output (returns null)
  return null;
}
