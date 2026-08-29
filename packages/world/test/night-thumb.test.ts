import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  NIGHT_SURFACE,
  classifyThumbZone,
  isLowGlareNightToken,
  isOneHandedAffordance,
} from "../src/index.ts";

describe("TASK-1007 — 3AM Thumb Arc & Night Surface (PRD 56, PRD 8.4)", () => {
  const standardPhone = { width: 393, height: 852 }; // iPhone standard

  it("places bottom capture affordances inside the natural thumb zone", () => {
    // Hold to talk button near bottom (y = 720, height = 64)
    const micButton = { x: 160, y: 720, width: 73, height: 64 };
    assert.equal(classifyThumbZone(micButton, standardPhone), "natural");
    assert.equal(isOneHandedAffordance(micButton, standardPhone), true);

    // Camera quick shutter (y = 650)
    const shutter = { x: 160, y: 650, width: 73, height: 64 };
    assert.equal(classifyThumbZone(shutter, standardPhone), "natural");
  });

  it("identifies top navigation elements as stretch requiring two hands", () => {
    const topBar = { x: 16, y: 44, width: 44, height: 44 };
    assert.equal(classifyThumbZone(topBar, standardPhone), "stretch");
    assert.equal(isOneHandedAffordance(topBar, standardPhone), false);
  });

  it("asserts night surface uses true OLED black ground", () => {
    assert.equal(NIGHT_SURFACE.ground, "#000000");
  });

  it("proves all night surface tokens are low-glare (< 0.35 luminance)", () => {
    for (const [name, colorHex] of Object.entries(NIGHT_SURFACE)) {
      assert.equal(
        isLowGlareNightToken(colorHex),
        true,
        `Night surface token '${name}' (${colorHex}) exceeded maximum 3AM low-glare luminance threshold`
      );
    }
  });
});
