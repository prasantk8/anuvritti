# CLAUDE.md - Production Operational Framework

## 1. Principles
- Architecture: DDD, Clean Architecture, Hexagonal.
- Code Quality: Type‑safe, DRY, SOLID, explicit error handling (Result/Either).
- Testing: TDD – coverage ≥ 90% unit, ≥ 80% integration, with E2E.
- Security: 12‑Factor, zero secrets, least‑privilege RBAC.

## 2. Dynamic Context & Memory
- Use `Grep`/`Glob` to target specific modules; never scan whole repo.
- Always run modular tests before and after code changes.

## 3. Tracker Protocol
- Read `tracker.json` before each operation; update after.
- States: "pending" → "in_progress" → "completed" | "blocked".
- On completion, run tests, lint, and record changed files/commit hash.
