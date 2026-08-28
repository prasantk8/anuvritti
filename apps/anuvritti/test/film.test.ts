import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import type { FilmMaterial, Instant } from "@anuvritti/client";

import { MADE_OF, shelveFilm } from "../src/model/film.ts";

function material(at: string, kind: FilmMaterial["kind"]): FilmMaterial {
  return { kind, captured_at: at as Instant };
}

describe("this year's film shelf", () => {
  it("keeps capture order and uses months as its only structure", () => {
    const shelf = shelveFilm([
      material("2026-01-02T08:00:00Z", "RECORDING"),
      material("2026-01-20T08:00:00Z", "SPARK"),
      material("2026-03-01T08:00:00Z", "RECORDING"),
    ]);
    assert.deepEqual(shelf.map(({ named }) => named), ["January 2026", "March 2026"]);
    assert.deepEqual(shelf[0]?.materials.map(({ kind }) => kind), ["RECORDING", "SPARK"]);
    assert.deepEqual(Object.keys(shelf[0]!).sort(), ["materials", "named"]);
  });

  it("says one finished sentence and carries no progress language", () => {
    assert.equal(MADE_OF, "This is what the film is made of.");
    assert.ok(!/count|scene|minute|percent|keep going|more|progress/i.test(MADE_OF));
  });

  it("never turns timestamps into arithmetic", () => {
    const source = readFileSync(new URL("../src/model/film.ts", import.meta.url), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "");
    for (const forbidden of ["new Date", "Date.parse", "getTime", "Date.now"]) {
      assert.ok(!source.includes(forbidden), forbidden);
    }
  });
});
