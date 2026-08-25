# ADR-0002 — `Result[T, E]` instead of exceptions for expected failures

**Status:** Accepted · **Date:** 2026-08-25 · **Context:** CLAUDE.md §1

## Decision
Domain and application operations return `Result[T, DomainError]`. Exceptions are reserved for
programmer errors and infrastructure faults. The HTTP adapter is the single place that turns
`Err` into a status code.

## Consequences
- (+) Failure modes are in the type signature; every one is enumerated in `docs/contracts/errors.md`.
- (+) "Illegal Spark transition" becomes ordinary data, not control flow.
- (−) Verbose call sites; mitigated by `Result.map` / `Result.and_then`.
