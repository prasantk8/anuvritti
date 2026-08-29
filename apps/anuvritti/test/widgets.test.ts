import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  DAILY_PROMPTS,
  RightNowWidgetManager,
  buildRightNowWidgetPayload,
  getPromptForDate,
  type WidgetStorageBridge,
} from "../src/widgets/right-now-widget.ts";

function makeMockBridge(): WidgetStorageBridge & { files: Map<string, string> } {
  const files = new Map<string, string>();
  return {
    files,
    async writeWidgetState(filename: string, json: string) {
      files.set(filename, json);
    },
    async readWidgetState(filename: string) {
      return files.get(filename) ?? null;
    },
  };
}

describe("TASK-1005 — Right Now Widgets (PRD 18, PRD 8.4)", () => {
  it("builds consistent lock screen and home screen widget payloads", () => {
    const payload = buildRightNowWidgetPayload({
      childId: "child-leo",
      childName: "Leo",
      dateStr: "2026-08-29",
    });

    assert.equal(payload.childName, "Leo");
    assert.ok(payload.prompt.length > 0);
    assert.equal(payload.deepLink.startsWith("anuvritti://right-now"), true);
    assert.equal(payload.deepLink.includes("childId=child-leo"), true);

    // Lock screen layout
    assert.equal(payload.lockScreen.accessoryRectangularTitle, "Right Now · Leo");
    assert.equal(payload.lockScreen.accessoryRectangularBody, payload.prompt);

    // Home screen layout
    assert.equal(payload.homeScreen.familyHeadline, "Today with Leo");
    assert.equal(payload.homeScreen.question, payload.prompt);
  });

  it("rotates prompts deterministically by date", () => {
    const p1 = getPromptForDate("2026-08-29");
    const p1Again = getPromptForDate("2026-08-29");
    const p2 = getPromptForDate("2026-08-30");

    assert.equal(p1, p1Again);
    assert.ok(DAILY_PROMPTS.includes(p1 as any));
    assert.ok(DAILY_PROMPTS.includes(p2 as any));
  });

  it("carries no guilt, streaks, counters or exclamation marks across any widget copy", () => {
    const testDates = ["2026-01-01", "2026-06-15", "2026-12-31", "2027-03-20"];
    const forbidden = ["streak", "consecutive", "missed", "hurry", "due", "points", "goal", "!"];

    for (const d of testDates) {
      const payload = buildRightNowWidgetPayload({
        childId: "child-maya",
        childName: "Maya",
        dateStr: d,
      });

      const serialized = JSON.stringify(payload).toLowerCase();
      for (const word of forbidden) {
        assert.equal(
          serialized.includes(word),
          false,
          `Widget copy on ${d} contained forbidden word or punctuation: ${word}`
        );
      }
    }
  });

  it("synchronizes widget state through the shared storage bridge", async () => {
    const bridge = makeMockBridge();
    const manager = new RightNowWidgetManager(bridge);

    const saved = await manager.syncWidgetState({
      childId: "child-leo",
      childName: "Leo",
      dateStr: "2026-08-29",
    });

    assert.ok(bridge.files.has("right-now-widget.json"));
    const retrieved = await manager.getCurrentWidgetState();
    assert.deepEqual(retrieved, saved);
  });
});
