/**
 * Reading a machine's guess without letting it look like a fact (PRD §13, §42, ADR-0005).
 *
 * The contract types `Attributed.value` as `unknown`, and that is honest: OpenAPI cannot say
 * "the value's type depends on which field this is". Rather than lie about it in the
 * generated types, the narrowing happens here, once, with a runtime check - so the app never
 * writes `spark.intent.value as IntentType` at twenty call sites, which is the version of
 * this where one of them is wrong.
 *
 * `confidence` is carried through deliberately. PRD §8.7: low confidence must be shown as a
 * question, never as a statement, and an interface that cannot see the number cannot obey.
 * This is not a contradiction of TASK-507 - a confidence is a fact about the *machine*, and
 * the rule is about counting a *family*.
 */

import type { AgeRange, Attributed, IntentType, Spark } from "../generated/contract.ts";
import { INTENT_TYPE_VALUES } from "../generated/contract.ts";

/** An inferred field, narrowed to the type it actually holds. */
export interface Inferred<T> {
  readonly value: T;
  readonly source: "HUMAN" | "AI" | "DEFAULT";
  readonly confidence: number;
  readonly humanOverride: boolean;
}

/** Below this, the interface must phrase it as a question (PRD §8.7). */
export const LOW_CONFIDENCE = 0.5;

export function isUncertain(field: Attributed): boolean {
  return field.source === "AI" && field.confidence < LOW_CONFIDENCE;
}

/** A human said so. That is the end of the discussion, and the interface must not re-ask. */
export function isStated(field: Attributed): boolean {
  return field.human_override;
}

function shape<T>(field: Attributed, value: T): Inferred<T> {
  return {
    value,
    source: field.source,
    confidence: field.confidence,
    humanOverride: field.human_override,
  };
}

const INTENTS: ReadonlySet<string> = new Set(INTENT_TYPE_VALUES);

export function intentOf(spark: Spark): Inferred<IntentType> | null {
  const value = spark.intent.value;
  if (typeof value !== "string" || !INTENTS.has(value)) return null;
  return shape(spark.intent, value as IntentType);
}

export function categoryOf(spark: Spark): Inferred<string> | null {
  const value = spark.category.value;
  return typeof value === "string" ? shape(spark.category, value) : null;
}

export function ageRangeOf(spark: Spark): Inferred<AgeRange> | null {
  const field = spark.age_range;
  if (!field) return null;
  const value = field.value as Partial<AgeRange> | null;
  if (!value || typeof value.min_years !== "number" || typeof value.max_years !== "number") {
    return null;
  }
  return shape(field, { min_years: value.min_years, max_years: value.max_years });
}

/**
 * How an age range is said out loud.
 *
 * "for 5 to 8 year olds" rather than "5-8", because the second one is a filter and the
 * first one is a sentence. These numbers are about a child's development, not a tally of
 * what a parent did or failed to do, so they are allowed to be numbers.
 */
export function ageRangeSaid(range: AgeRange): string {
  if (range.min_years === range.max_years) return `for ${range.min_years} year olds`;
  return `for ${range.min_years} to ${range.max_years} year olds`;
}
