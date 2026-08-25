# ADR-0005 — Every AI-derived field carries value/source/confidence/human_override

**Status:** Accepted · **Date:** 2026-08-25 · **Context:** PRD §13, §42, §8.7

## Decision
Model inferred fields as `Attributed[T]` = (value, source, confidence, human_override) and persist
them as four columns, not a JSON blob. §8.7 separates *recorded truth*, *human interpretation* and
*AI interpretation*; the type makes that distinction unforgeable.

## Consequences
- (+) Provenance is queryable and cannot be silently dropped by a serializer.
- (+) `human_override=True` short-circuits re-inference — the human is never overwritten.
- (−) Wider table. Accepted: honesty about AI is a product requirement, not a nicety.
