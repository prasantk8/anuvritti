/**
 * Translator with Family Vocabulary Substitution (PRD 40).
 */

import {
  LOCALE_CATALOGS,
  type StringCatalog,
  type SupportedLocale,
} from "./catalog.ts";

export interface FamilyVocabulary {
  [word: string]: string;
}

export class FamilyTranslator {
  private _locale: SupportedLocale;
  private _catalog: StringCatalog;
  private _familyWords: FamilyVocabulary;

  constructor(
    locale: SupportedLocale = "en",
    familyWords: FamilyVocabulary = {},
    customCatalog?: Partial<StringCatalog>
  ) {
    this._locale = locale;
    const base = LOCALE_CATALOGS[locale] || LOCALE_CATALOGS.en;
    this._catalog = customCatalog ? { ...base, ...customCatalog } : base;
    this._familyWords = familyWords;
  }

  get locale(): SupportedLocale {
    return this._locale;
  }

  get catalog(): StringCatalog {
    return this._catalog;
  }

  interpolate(
    template: string,
    variables: Record<string, string | number> = {}
  ): string {
    let result = template;
    for (const [key, value] of Object.entries(variables)) {
      result = result.replaceAll(`{${key}}`, String(value));
    }
    // Apply family-specific words (PRD 40)
    for (const [stdWord, familyWord] of Object.entries(this._familyWords)) {
      result = result.replaceAll(stdWord, familyWord);
    }
    return result;
  }
}

export function createTranslator(
  locale: SupportedLocale = "en",
  familyWords: FamilyVocabulary = {}
): FamilyTranslator {
  return new FamilyTranslator(locale, familyWords);
}
