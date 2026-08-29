import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  a11yLabels,
  calculateContrastRatio,
  computeDynamicType,
  resolveMotionDuration,
} from "../src/a11y/accessibility.ts";

describe("TASK-1006 — Proven Accessibility (PRD 56, PRD 27)", () => {
  it("generates comprehensive screen reader labels for Spark objects", () => {
    const sparkProps = a11yLabels.spark({
      title: "Building treehouse in the backyard",
      whyText: "He asked if birds could visit our balcony",
      subjectChildName: "Leo",
    });

    assert.equal(sparkProps.accessible, true);
    assert.equal(sparkProps.accessibilityRole, "summary");
    assert.ok(sparkProps.accessibilityLabel.includes("Building treehouse"));
    assert.ok(sparkProps.accessibilityLabel.includes("For Leo"));
    assert.ok(sparkProps.accessibilityLabel.includes("He asked if birds could visit"));
  });

  it("announces voice recording states clearly for screen readers", () => {
    const idle = a11yLabels.holdToTalk({ isRecording: false, elapsedSeconds: 0 });
    assert.equal(idle.accessibilityRole, "button");
    assert.ok(idle.accessibilityLabel.includes("Hold to talk"));

    const live = a11yLabels.holdToTalk({ isRecording: true, elapsedSeconds: 4 });
    assert.equal(live.accessibilityRole, "button");
    assert.equal(live.accessibilityState?.busy, true);
    assert.ok(live.accessibilityLabel.includes("4 seconds elapsed"));
    assert.ok(live.accessibilityLabel.includes("Release to save"));
  });

  it("scales dynamic type up to 200% while maintaining minimum touch targets", () => {
    const normal = computeDynamicType(16, 1.0);
    assert.equal(normal.fontSize, 16);
    assert.ok(normal.minTouchTarget >= 44);

    const extraLarge = computeDynamicType(16, 2.0);
    assert.equal(extraLarge.fontSize, 32);
    assert.equal(extraLarge.lineHeight >= 40, true);
    assert.ok(extraLarge.minTouchTarget >= 44);
  });

  it("honours reduced motion preferences by setting durations to zero", () => {
    const normalDuration = resolveMotionDuration(300, false);
    assert.equal(normalDuration, 300);

    const reducedDuration = resolveMotionDuration(300, true);
    assert.equal(reducedDuration, 0);
  });

  it("proves text-on-ground contrast meets WCAG AAA standards", () => {
    // White on dark ground (#121212)
    const darkRatio = calculateContrastRatio("#FFFFFF", "#121212");
    assert.ok(darkRatio >= 15.0, `Dark theme contrast ratio ${darkRatio} should be >= 15.0`);

    // Black on cream ground (#F9F8F6)
    const lightRatio = calculateContrastRatio("#1C1B1A", "#F9F8F6");
    assert.ok(lightRatio >= 14.0, `Light theme contrast ratio ${lightRatio} should be >= 14.0`);
  });
});
