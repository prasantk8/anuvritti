# ADR-0003 — SQLite as the V0 store

**Status:** Accepted · **Date:** 2026-08-25 · **Context:** PRD §44 "local-first or privacy-first"

## Decision
SQLite via stdlib `sqlite3` behind repository ports. Hand-written idempotent migrations,
no ORM. Domain objects never see a row or a cursor.

## Thread safety
Sync FastAPI endpoints run in a threadpool, so one `sqlite3.Connection` really is reached by
several requests at once. `check_same_thread=False` permits that but does not make it correct —
concurrent `execute` on one connection raises `InterfaceError: bad parameter or other API misuse`
and can interleave a transaction. `GuardedConnection` therefore serialises access behind a
re-entrant lock, and `execute` materialises rows inside that lock rather than returning a live
cursor. `SqliteUnitOfWork` holds the same lock for a whole transaction. SQLite is single-writer
regardless, so a one-family product pays nothing for this.

## Consequences
- (+) The whole family archive is one file the family owns — the strongest reading of §44.
- (+) Zero infra to run the 30-day validation test (§54).
- (−) Single-writer, now explicitly serialised. Acceptable for one family; `WAL` mode enabled.
- (−) No vector search; V0 search is keyword + facet (§48 F5 lists only such queries).
