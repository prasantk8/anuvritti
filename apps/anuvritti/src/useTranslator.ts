/**
 * Hook for translating UI copy into the family's language (PRD 40, PRD 56).
 */

import { useMemo } from "react";
import { createTranslator, type FamilyVocabulary, type SupportedLocale, type FamilyTranslator } from "@anuvritti/world";

export function useTranslator(
  locale: SupportedLocale = "en",
  familyWords: FamilyVocabulary = {}
): FamilyTranslator {
  return useMemo(() => createTranslator(locale, familyWords), [locale, familyWords]);
}
