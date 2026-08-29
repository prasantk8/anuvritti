"""Schema migrations: a forward path, a rehearsed rollback, and safety verification.

(TASK-1101, HARDENING 5.4, PRD 8.6.)

A migration applied to a family's archive is rehearsed against an isolated copy before
touching the live database. If anything fails in rehearsal, the live archive is never
touched. Every migration provides an exact rollback step.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Final

# Forward migration scripts
from anuvritti.adapters.persistence.schema import (
    _MIGRATIONS,
    SCHEMA_VERSION,
    GuardedConnection,
    connect,
)
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.result import Err, Ok, Result

# Rehearsed rollback scripts for each schema version
_ROLLBACKS: Final[dict[int, str]] = {
    6: """
    DROP INDEX IF EXISTS idx_render_job_status;
    DROP INDEX IF EXISTS idx_render_job_family_spec;
    DROP TABLE IF EXISTS render_job;
    """,
    # TASK-819. The index goes with the table; a sealed message's ciphertext lives in the
    # file named by storage_key, and dropping this row makes it unreadable rather than
    # deleted. That is the correct outcome for a rollback: a schema step that could erase a
    # parent's sealed words would be a data-loss bug wearing a rehearsal's clothes.
    5: """
    DROP INDEX IF EXISTS idx_future_inbox_family;
    DROP TABLE IF EXISTS future_inbox;
    """,
    4: """
    DROP TABLE IF EXISTS lexicon_term;
    """,
    3: """
    DROP TABLE IF EXISTS voice_note;
    """,
    2: """
    DROP TABLE IF EXISTS idempotency;
    DROP TABLE IF EXISTS pairing_attempt;
    DROP TABLE IF EXISTS pairing_request;
    DROP TABLE IF EXISTS device;
    """,
    1: """
    DROP TABLE IF EXISTS domain_event;
    DROP TABLE IF EXISTS media;
    DROP TABLE IF EXISTS right_now;
    DROP TABLE IF EXISTS little_thing;
    DROP TABLE IF EXISTS moment;
    DROP TABLE IF EXISTS spark;
    DROP TABLE IF EXISTS child_profile;
    DROP TABLE IF EXISTS member;
    DROP TABLE IF EXISTS family;
    """,
}


def get_version(conn: GuardedConnection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def migrate_to(conn: GuardedConnection, target_version: int) -> Result[int, DomainError]:
    """Migrate the database forwards or backwards to target_version."""
    if target_version < 0 or target_version > len(_MIGRATIONS):
        return Err(
            DomainError(
                ErrorCode.VALIDATION_FAILED,
                f"invalid target migration version {target_version}; max is {len(_MIGRATIONS)}",
            )
        )

    current = get_version(conn)

    if target_version > current:
        # Forward migration
        for v in range(current + 1, target_version + 1):
            try:
                conn.executescript(_MIGRATIONS[v - 1])
                conn.execute(f"PRAGMA user_version = {v}")
            except Exception as exc:
                return Err(
                    DomainError(
                        ErrorCode.CONFLICT,
                        f"migration to version {v} failed: {exc}",
                        {"target_version": target_version, "failed_at": v},
                    )
                )
    elif target_version < current:
        # Rollback migration
        for v in range(current, target_version, -1):
            rollback_script = _ROLLBACKS.get(v)
            if not rollback_script:
                return Err(
                    DomainError(
                        ErrorCode.CONFLICT,
                        f"no rollback script defined for schema version {v}",
                        {"version": v},
                    )
                )
            try:
                conn.executescript(rollback_script)
                conn.execute(f"PRAGMA user_version = {v - 1}")
            except Exception as exc:
                return Err(
                    DomainError(
                        ErrorCode.CONFLICT,
                        f"rollback from version {v} failed: {exc}",
                        {"target_version": target_version, "failed_at": v},
                    )
                )

    # Verify integrity after migration
    row = conn.execute("PRAGMA quick_check").fetchone()
    if not row or row[0] != "ok":
        return Err(
            DomainError(
                ErrorCode.CONFLICT,
                f"integrity check failed after migration: {row[0] if row else 'unknown error'}",
            )
        )

    return Ok(get_version(conn))


def rehearse_and_migrate(
    live_db_path: Path, target_version: int = SCHEMA_VERSION
) -> Result[int, DomainError]:
    """Rehearse migration on an isolated copy of the database before applying to live."""
    live_path = Path(live_db_path)
    if not live_path.exists():
        # New database, just connect and migrate directly
        conn = connect(str(live_path))
        try:
            return migrate_to(conn, target_version)
        finally:
            conn.close()

    with tempfile.TemporaryDirectory() as td:
        scratch_db = Path(td) / "rehearsal.db"

        # 1. Take consistent online backup snapshot to scratch DB
        live_conn = connect(str(live_path))
        try:
            with live_conn.lock:
                scratch_raw = connect(str(scratch_db))
                try:
                    with scratch_raw.lock:
                        live_conn._raw.backup(scratch_raw._raw)
                finally:
                    scratch_raw.close()
        finally:
            live_conn.close()

        # 2. Rehearse migration on the scratch snapshot
        rehearsal_conn = connect(str(scratch_db))
        try:
            rehearsal_result = migrate_to(rehearsal_conn, target_version)
            if rehearsal_result.is_err():
                return Err(
                    DomainError(
                        ErrorCode.CONFLICT,
                        "Migration rehearsal failed; live database untouched: "
                        f"{rehearsal_result.unwrap_err().message}",
                        rehearsal_result.unwrap_err().details,
                    )
                )
        finally:
            rehearsal_conn.close()

        # 3. Rehearsal passed! Apply to live database
        target_conn = connect(str(live_path))
        try:
            return migrate_to(target_conn, target_version)
        finally:
            target_conn.close()
