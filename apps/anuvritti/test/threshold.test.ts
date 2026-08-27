import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { thresholdStage, visiblePairingCode } from "../src/model/threshold.ts";

const pair = readFileSync(new URL("../app/pair.tsx", import.meta.url), "utf8");
const threshold = readFileSync(new URL("../app/threshold.tsx", import.meta.url), "utf8");
const pairingCode = readFileSync(new URL("../app/pairing-code.tsx", import.meta.url), "utf8");
const layout = readFileSync(new URL("../app/_layout.tsx", import.meta.url), "utf8");

describe("the threshold", () => {
  it("asks for the child before it asks for a share", () => {
    assert.equal(thresholdStage({ familyId: "fam-1" }), "child");
    assert.equal(thresholdStage({ familyId: "fam-1", childName: "Aarav" }), "share");
  });

  it("creates the child through the documented family route", () => {
    assert.match(threshold, /api\.addChild\(threshold\.familyId/);
    assert.match(threshold, /display_name/);
    assert.match(threshold, /date_of_birth/);
  });

  it("finishes only after an incoming share has really been saved", () => {
    assert.match(threshold, /justSaved/);
    assert.match(threshold, /finishThreshold/);
  });

  it("is resumed by the root instead of flashing the empty home", () => {
    assert.match(layout, /showsThreshold/);
    assert.match(layout, /name="threshold"/);
  });

  it("has no tour, step count, progress, or rendered age", () => {
    const code = threshold.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    assert.doesNotMatch(code, /\bstep\b|progress|age_years|\d+\s+of\s+\d+/i);
  });

  it("family creation proceeds directly to the child", () => {
    assert.doesNotMatch(pair, /yourName|label="And you\?"/);
    assert.match(pair, /beginThreshold\(result\.value\.id\)/);
  });
});

describe("the pairing sheet", () => {
  it("shows exactly the eight issued characters", () => {
    assert.equal(visiblePairingCode("abcd-1234"), "ABCD1234");
    assert.equal(visiblePairingCode("too-long-code"), "TOOLONGC");
  });

  it("uses the mono face at year size and expires itself", () => {
    assert.match(pairingCode, /world\.font\.mono/);
    assert.match(pairingCode, /world\.type\.year/);
    assert.match(pairingCode, /expires_in_seconds/);
    assert.match(pairingCode, /setTimeout/);
  });

  it("renders no explanatory copy beside a live code", () => {
    assert.match(pairingCode, /<Text style=\{styles\.code\}>\{code\}<\/Text>/);
    assert.equal((pairingCode.match(/<Text\b/g) ?? []).length, 1);
  });
});
