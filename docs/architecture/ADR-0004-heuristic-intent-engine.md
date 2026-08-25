# ADR-0004 — Deterministic heuristic intent engine behind a port

**Status:** Accepted · **Date:** 2026-08-25 · **Context:** PRD §8.1, §13, §49

## Context
§13 makes intent understanding the core AI capability, but §8.1 says "Human Before AI" and §49
forbids advanced agents in V0.

## Decision
`IntentEngine` is a **port**. V0 ships `HeuristicIntentEngine`: rule/lexicon based, offline,
deterministic, emitting calibrated `Confidence` per field. An LLM adapter may be added in V1
without touching domain or application code.

## Consequences
- (+) No third-party data egress — satisfies "no public-model training by default" (§44) absolutely.
- (+) Tests are deterministic; confidence calibration is assertable.
- (−) Lower accuracy than an LLM. Mitigated: low confidence simply means the field is shown as
  a suggestion, and human override always wins (§13).
