/**
 * Right Now Widget (PRD 18, PRD 8.4).
 *
 * The most frequent interaction in Anuvritti is answering a single gentle question
 * about a child today. Surfacing this question directly on the Lock Screen and Home Screen
 * widgets allows the parent to notice and reflect without an app launch.
 *
 * Rules (PRD 8.4, PRD 47):
 * - No streaks, no numbers, no red dots, no exclamation marks.
 * - Deep links directly into the one-sentence capture response.
 * - Rotates daily on the device without network requirement.
 */

export interface RightNowWidgetPayload {
  childId: string;
  childName: string;
  prompt: string;
  date: string;
  deepLink: string;
  lockScreen: {
    accessoryCircularText: string;
    accessoryRectangularTitle: string;
    accessoryRectangularBody: string;
  };
  homeScreen: {
    familyHeadline: string;
    question: string;
    tapPrompt: string;
  };
}

export const DAILY_PROMPTS = [
  "What made them laugh out loud today?",
  "What is their favorite thing to wear right now?",
  "What word do they pronounce in their own special way?",
  "What are they currently obsessed with building or playing?",
  "Who is their favorite person or toy this week?",
  "What is their bedtime routine question tonight?",
  "What song do they keep humming or asking to hear?",
] as const;

export function getPromptForDate(dateStr: string): string {
  let hash = 0;
  for (let i = 0; i < dateStr.length; i++) {
    hash = (hash * 31 + dateStr.charCodeAt(i)) >>> 0;
  }
  return DAILY_PROMPTS[hash % DAILY_PROMPTS.length] as string;
}

export function buildRightNowWidgetPayload(params: {
  childId: string;
  childName: string;
  dateStr: string;
  customPrompt?: string;
}): RightNowWidgetPayload {
  const prompt = params.customPrompt || getPromptForDate(params.dateStr);
  const deepLink = `anuvritti://right-now?childId=${encodeURIComponent(
    params.childId
  )}&date=${encodeURIComponent(params.dateStr)}`;

  return {
    childId: params.childId,
    childName: params.childName,
    prompt,
    date: params.dateStr,
    deepLink,
    lockScreen: {
      accessoryCircularText: params.childName.slice(0, 3).toUpperCase(),
      accessoryRectangularTitle: `Right Now · ${params.childName}`,
      accessoryRectangularBody: prompt,
    },
    homeScreen: {
      familyHeadline: `Today with ${params.childName}`,
      question: prompt,
      tapPrompt: "Tap to note one sentence",
    },
  };
}

export interface WidgetStorageBridge {
  writeWidgetState(filename: string, json: string): Promise<void>;
  readWidgetState(filename: string): Promise<string | null>;
}

export class RightNowWidgetManager {
  private _bridge: WidgetStorageBridge;

  constructor(bridge: WidgetStorageBridge) {
    this._bridge = bridge;
  }

  async syncWidgetState(params: {
    childId: string;
    childName: string;
    dateStr: string;
    customPrompt?: string;
  }): Promise<RightNowWidgetPayload> {
    const payload = buildRightNowWidgetPayload(params);
    await this._bridge.writeWidgetState("right-now-widget.json", JSON.stringify(payload));
    return payload;
  }

  async getCurrentWidgetState(): Promise<RightNowWidgetPayload | null> {
    const raw = await this._bridge.readWidgetState("right-now-widget.json");
    if (!raw) return null;
    try {
      return JSON.parse(raw) as RightNowWidgetPayload;
    } catch {
      return null;
    }
  }
}
