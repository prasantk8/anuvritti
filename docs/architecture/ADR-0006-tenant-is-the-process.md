# ADR-0006 — The Tenant Is The Process

**Status:** Accepted · **Date:** 2026-08-29 · **Context:** ADR-0003, PRD §44, TASK-901, TASK-905, TASK-906, TASK-909

## Context
Traditional SaaS systems attempt multi-tenancy inside a single shared application process and a single database cluster, relying on application-level filtering (`WHERE family_id = ?`) and row-level security (RLS) to enforce isolation.

For a family archive holding childhood voice notes, private photographs, and daily intimate moments, a single software bug or query mistake in a shared-database model risks catastrophic cross-family data leakage. Furthermore, PRD §44 establishes that privacy is an architectural guarantee rather than an operational policy.

ADR-0003 established SQLite as the local-first storage engine. We now formalize the deployment boundary for multi-tenancy.

## Decision
**The tenant is the process.**

1. **One Family, One Process, One Database**:
   - Each family's server is an independent containerized process with its own dedicated SQLite file (`anuvritti.db`) and its own encrypted media directory.
   - There is no shared database containing multiple families' archives.
   - If multiple families are hosted by a platform provider, each family runs as an isolated container/microVM (e.g. systemd service, Docker container, or Fly.io machine).

2. **Authentication as Instance Pairing**:
   - Authentication on a given Anuvritti server is strictly: *"Is this device authorized to pair with this family's box?"*
   - Bootstrap (`POST /v1/families`) creates the single family on that box and pairs the founding device. Once bootstrapped in production, unauthenticated family creation is permanently closed.
   - Joining devices use single-use pairing codes (`POST /v1/pairing/claim`) issued by an existing trusted device.

3. **Superseded Assumptions**:
   - This decision supersedes the centralized multi-family-on-one-server assumptions under TASK-901, 1105, 1112, and 1211. TASK-1211 is resolved and closed by this architecture.

## Consequences
- (+) **Absolute Tenant Isolation**: Cross-tenant data leaks are physically impossible at the database and memory layer; one family's query cannot see or touch another family's storage.
- (+) **Atomic Backup & Portability**: Backup and restore (`TASK-905`, `scripts/backup.sh`) operates on clean single-family SQLite files with zero cross-tenant locking.
- (+) **Independent Encryption Keys**: Each family container mounts its own independent Fernet key (`ANUVRITTI_MEDIA_KEY`), ensuring compromise of one key never affects another family.
- (+) **True Deletion Sovereignty**: Family data deletion is an atomic filesystem wipe (`rm -rf`) with zero remnants or dangling foreign keys.
- (−) Higher per-tenant process overhead compared to monolithic multi-tenant pools. Accepted: for childhood memory preservation, absolute privacy guarantees completely outweigh compute packing density.
