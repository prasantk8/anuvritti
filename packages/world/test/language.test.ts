import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  LOCALE_CATALOGS,
  createTranslator,
  type SupportedLocale,
} from "../src/language/index.ts";

describe("TASK-1012 — The Family's Own Language (PRD 40, PRD 56)", () => {
  it("provides complete string catalog across supported locales", () => {
    const locales: SupportedLocale[] = ["en", "hi", "es"];
    for (const loc of locales) {
      const translator = createTranslator(loc);
      const cat = translator.catalog;
      assert.ok(cat.today.emptyHeadline.length > 0);
      assert.ok(cat.voice.holdToRecord.length > 0);
      assert.ok(cat.returns.headline.length > 0);
      assert.ok(cat.returns.optionLived.length > 0);
    }
  });

  it("carries no guilt, urgency, streaks, or exclamation marks across any translation catalog", () => {
    const forbidden = ["streak", "consecutive", "missed", "hurry", "due", "points", "goal", "!"];
    for (const [locale, cat] of Object.entries(LOCALE_CATALOGS)) {
      const serialized = JSON.stringify(cat).toLowerCase();
      for (const word of forbidden) {
        assert.equal(
          serialized.includes(word),
          false,
          `Catalog for locale '${locale}' contained forbidden text/punctuation: ${word}`
        );
      }
    }
  });

  it("interpolates variables cleanly", () => {
    const translator = createTranslator("en");
    const formatted = translator.interpolate(translator.catalog.returns.headline, {
      childName: "Aarav",
    });
    assert.equal(formatted, "Something brought back for Aarav");
  });

  it("applies the family's own vocabulary custom words (PRD 40)", () => {
    const translator = createTranslator("hi", {
      "संग्रह": "खज़ाना", // Family prefers calling the archive 'Khazana'
    });
    const template = translator.catalog.today.emptyBody;
    const translated = translator.interpolate(template);
    assert.ok(translated.includes("खज़ाना"));
    assert.equal(translated.includes("संग्रह"), false);
  });
});
