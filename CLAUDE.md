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
- One task per chat. Start with `python3 scripts/tracker.py brief TASK-ID` (the task, its deps' files, what
  it unlocks), then read whatever the work needs. Update with `tracker.py set`; `tracker.json` is 130 KB, so
  query it (`brief`, `next`, `status`) rather than opening it whole.
- States: "pending" → "in_progress" → "completed" | "blocked".
- On completion, run `make check` (all gates, not just the task's own `verification_command`), record
  every changed file with `--files`, say what is true now with `--note`, and check the board with
  `tracker.py audit`.

## 4. Definition of Done
`docs/AGENT-GUIDE.md` is binding. In short: it is not done until something in production calls it
(`tests/architecture/test_reachability.py`), it is proven against the real migrated schema through the
real app rather than a schema the test invented, every gate in `make check` is green, and no document
describes something that did not happen.
