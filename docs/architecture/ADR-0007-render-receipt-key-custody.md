# ADR-0007 — Durable Family Render-Receipt Key Custody

**Status:** Accepted · **Date:** 2026-08-29 · **Context:** PRD §44, §47, §55.5, TASK-722, TASK-905

## Context
When a family compiles a commemorative film or exports an archive bundle, a cryptographic render receipt (`receipt.json`) is generated and signed with an offline family authenticity key (Ed25519) to anchor provenance and prove that no frames or audio clips were fabricated, altered, or hallucinated.

We must define key custody: how this signing key is generated, stored, backed up, recovered, rotated, and accessed across multiple devices without creating vendor lock-in or fragile cloud dependencies.

## Decision
1. **Key Generation & Storage Topology**:
   - During family bootstrap (`POST /v1/families`), a unique Ed25519 keypair is generated on the family's server.
   - The private signing key (`receipt_signing_key`) is stored locally at rest and never transmitted over public networks or exposed to clients.
   - The public verification key (`receipt_verify_key`) is exposed in pairing payloads, embedded into exported film packages, and bundled in `provenance.json`.

2. **Backup & Disaster Recovery (Connection to TASK-905 & CONTINUITY.md)**:
   - The signing key is included in the family's encrypted configuration and database backup archive created by `scripts/backup.sh`.
   - Restoration via `scripts/restore.sh` reinstates the exact signing key alongside the SQLite archive and encrypted media files.
   - Key escrow instructions are documented in the 10-line family continuity guide (`docs/CONTINUITY.md`).

3. **Multi-Device Verification**:
   - Paired devices (parents, co-parents, grandparents) receive the public verification key during pairing.
   - Verification of exported films and receipts occurs client-side using purely offline public key cryptography.

4. **Rotation Semantics**:
   - When a parent requests key rotation, a new Ed25519 keypair is generated.
   - The server creates and records a signed *Key Transition Certificate* where the previous key signs the new public key, preserving an unbroken chain of custody for older historical films.

5. **Loss Semantics**:
   - If a signing key is lost due to total server destruction without backup, historical films already signed remain permanently valid (since their receipts contain the old public key hash).
   - A newly bootstrapped server provisions a new signing key. Loss of the receipt signing key never impairs access to the raw photographs, recordings, or SQLite memory rows.

## Consequences
- (+) Fully autonomous, local-first cryptographic custody with zero third-party CA or cloud dependencies.
- (+) Rehearsed backup/restore roundtrips (`TASK-905`) seamlessly preserve receipt signing capacity.
- (+) Client devices can verify film authenticity completely offline.
- (−) Requires family operator to maintain off-site backup of environment configuration or passphrases. Accepted: align with PRD §44 single-tenant sovereignty.
