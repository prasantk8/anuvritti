import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

const ROOT = join(import.meta.dirname, "../..");
const SITE_HTML = join(ROOT, "site", "index.html");

describe("memtara.com site", () => {
  it("exists and is well-formed HTML", () => {
    assert.ok(existsSync(SITE_HTML));
    const html = readFileSync(SITE_HTML, "utf8");
    assert.ok(html.includes("<!DOCTYPE html>"));
    assert.ok(html.includes("Memtara"));
  });

  it("manifesto of refusals matches constitution", () => {
    const html = readFileSync(SITE_HTML, "utf8");
    assert.ok(html.includes("No streaks"));
    assert.ok(html.includes("No nagging"));
    assert.ok(html.includes("Never held hostage"));
  });
});
