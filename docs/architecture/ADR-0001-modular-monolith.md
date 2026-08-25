# ADR-0001 — Modular monolith with hexagonal internals

**Status:** Accepted · **Date:** 2026-08-25 · **Context:** PRD §48, §51

## Context
V0 serves exactly one family (§48). V2 may become a "Family Presence OS" (§51) with
co-parents, grandparents and child participation.

## Decision
Ship **one deployable** structured as bounded-context packages with ports & adapters.
Context boundaries are enforced as package boundaries plus an executable dependency-rule test.

## Consequences
- (+) No distributed-systems cost for a one-family product.
- (+) A later service split is a packaging change, not a rewrite.
- (−) Requires discipline; mitigated by `tests/architecture/test_dependency_rule.py`.
