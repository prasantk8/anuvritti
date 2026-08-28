"""SQLite schema and migrations (ADR-0003).

Hand-written and idempotent. No ORM: the domain must never learn what a row looks like,
and a family archive should be readable with `sqlite3` in twenty years without this
codebase existing.

Provenance is stored as discrete columns rather than a JSON blob, so a serializer change
can never quietly turn an AI guess into an apparent fact (ADR-0005).
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

SCHEMA_VERSION: Final = 4

_MIGRATIONS: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS family (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        created_at  TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS member (
        id            TEXT PRIMARY KEY,
        family_id     TEXT NOT NULL REFERENCES family(id) ON DELETE CASCADE,
        display_name  TEXT NOT NULL,
        role          TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS child_profile (
        id            TEXT PRIMARY KEY,
        family_id     TEXT NOT NULL REFERENCES family(id) ON DELETE CASCADE,
        member_id     TEXT NOT NULL,
        display_name  TEXT NOT NULL,
        date_of_birth TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS spark (
        id                    TEXT PRIMARY KEY,
        family_id             TEXT NOT NULL REFERENCES family(id) ON DELETE CASCADE,
        owner_id              TEXT NOT NULL,
        subject_child_id      TEXT,
        title                 TEXT NOT NULL,
        note                  TEXT,

        -- PRD 43: what survives when the link does not
        source_kind           TEXT NOT NULL,
        source_url            TEXT,
        source_creator        TEXT,
        source_title          TEXT,
        source_text           TEXT,
        source_media_id       TEXT,

        -- ADR-0005: four columns per inferred field, never a blob
        intent_value          TEXT NOT NULL,
        intent_source         TEXT NOT NULL,
        intent_confidence     REAL NOT NULL,
        intent_overridden     INTEGER NOT NULL,
        category_value        TEXT NOT NULL,
        category_source       TEXT NOT NULL,
        category_confidence   REAL NOT NULL,
        category_overridden   INTEGER NOT NULL,
        age_min               INTEGER,
        age_max               INTEGER,
        age_source            TEXT,
        age_confidence        REAL,
        age_overridden        INTEGER,

        tags_json             TEXT NOT NULL DEFAULT '[]',
        why_text              TEXT,
        why_voice_media_id    TEXT,
        why_recorded_at       TEXT,

        status                TEXT NOT NULL,
        visibility            TEXT NOT NULL,
        suggested_count       INTEGER NOT NULL DEFAULT 0,
        last_suggested_at     TEXT,
        snoozed_until         TEXT,
        created_at            TEXT NOT NULL,
        updated_at            TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_spark_family        ON spark(family_id);
    CREATE INDEX IF NOT EXISTS idx_spark_family_status ON spark(family_id, status);
    CREATE INDEX IF NOT EXISTS idx_spark_child         ON spark(family_id, subject_child_id);
    CREATE INDEX IF NOT EXISTS idx_spark_created       ON spark(family_id, created_at DESC);

    CREATE TABLE IF NOT EXISTS moment (
        id              TEXT PRIMARY KEY,
        family_id       TEXT NOT NULL REFERENCES family(id) ON DELETE CASCADE,
        spark_id        TEXT NOT NULL UNIQUE,
        happened_on     TEXT NOT NULL,
        reflection      TEXT,
        photo_media_id  TEXT,
        audio_media_id  TEXT,
        created_by      TEXT NOT NULL,
        created_at      TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_moment_family ON moment(family_id);

    CREATE TABLE IF NOT EXISTS little_thing (
        id                TEXT PRIMARY KEY,
        family_id         TEXT NOT NULL REFERENCES family(id) ON DELETE CASCADE,
        author_id         TEXT NOT NULL,
        subject_child_id  TEXT,
        text              TEXT,
        audio_media_id    TEXT,
        created_at        TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_little_thing_family ON little_thing(family_id);

    CREATE TABLE IF NOT EXISTS right_now (
        id           TEXT PRIMARY KEY,
        family_id    TEXT NOT NULL REFERENCES family(id) ON DELETE CASCADE,
        child_id     TEXT NOT NULL,
        prompt       TEXT NOT NULL,
        answer       TEXT NOT NULL,
        captured_at  TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_right_now_family ON right_now(family_id);

    CREATE TABLE IF NOT EXISTS media (
        id            TEXT PRIMARY KEY,
        family_id     TEXT NOT NULL,
        kind          TEXT NOT NULL,
        mime_type     TEXT NOT NULL,
        byte_size     INTEGER NOT NULL,
        content_hash  TEXT NOT NULL,
        storage_key   TEXT NOT NULL,
        encrypted     INTEGER NOT NULL,
        created_at    TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_media_family ON media(family_id);

    CREATE TABLE IF NOT EXISTS domain_event (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id     TEXT NOT NULL,
        aggregate_id  TEXT NOT NULL,
        name          TEXT NOT NULL,
        payload_json  TEXT NOT NULL,
        occurred_at   TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_event_family ON domain_event(family_id, occurred_at);
    """,
    """
    -- TASK-511. Paired devices close HARDENING 5.1: the token is the family.
    --
    -- Only fingerprints are stored. A stolen copy of this file yields no token and no
    -- pairing code - which is the point of keeping the archive in one portable file.
    CREATE TABLE IF NOT EXISTS device (
        id                 TEXT PRIMARY KEY,
        family_id          TEXT NOT NULL REFERENCES family(id) ON DELETE CASCADE,
        member_id          TEXT NOT NULL,
        display_name       TEXT NOT NULL,
        token_fingerprint  TEXT NOT NULL UNIQUE,
        created_at         TEXT NOT NULL,
        last_seen_at       TEXT,
        revoked_at         TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_device_family ON device(family_id);

    CREATE TABLE IF NOT EXISTS pairing_request (
        code_fingerprint  TEXT PRIMARY KEY,
        family_id         TEXT NOT NULL REFERENCES family(id) ON DELETE CASCADE,
        member_id         TEXT NOT NULL,
        created_at        TEXT NOT NULL,
        expires_at        TEXT NOT NULL,
        claimed_at        TEXT
    );

    -- The attempt ledger. A wrong guess matches no code, so there is no per-code counter
    -- to increment; the limit has to live here, across the whole pairing window.
    CREATE TABLE IF NOT EXISTS pairing_attempt (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        succeeded    INTEGER NOT NULL,
        occurred_at  TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_pairing_attempt_at ON pairing_attempt(occurred_at);

    -- TASK-509. What a phone that saved with no signal replays into.
    --
    -- `request_fingerprint` is what makes a replay safe rather than merely quiet: the same
    -- key carrying a different body is a client bug, and answering it with the first
    -- request's Spark would silently lose the second one.
    CREATE TABLE IF NOT EXISTS idempotency (
        key                  TEXT NOT NULL,
        family_id            TEXT NOT NULL REFERENCES family(id) ON DELETE CASCADE,
        request_fingerprint  TEXT NOT NULL,
        status_code          INTEGER NOT NULL,
        response_json        TEXT NOT NULL,
        created_at           TEXT NOT NULL,
        PRIMARY KEY (key, family_id)
    );

    CREATE INDEX IF NOT EXISTS idx_idempotency_family ON idempotency(family_id);
    """,
    """
    -- TASK-603. The recording is the artifact; the transcript is only an index.
    --
    -- The primary key is the media id, not a surrogate. That is the schema refusing to
    -- represent a transcript whose audio has gone: there is no row to hold one. It also
    -- means a media row deleted for a family takes its words with it, rather than leaving
    -- behind a paraphrase of something a parent said about their child.
    --
    -- Provenance is four discrete columns, the same shape ADR-0005 uses for every other
    -- inferred field, so no serializer can drop it and leave a machine's reading looking
    -- like a quotation.
    CREATE TABLE IF NOT EXISTS voice_note (
        media_id              TEXT PRIMARY KEY,
        family_id             TEXT NOT NULL REFERENCES family(id) ON DELETE CASCADE,
        author_id             TEXT NOT NULL,
        duration_seconds      REAL NOT NULL,
        recorded_at           TEXT NOT NULL,

        transcript_text       TEXT,
        transcript_source     TEXT,
        transcript_confidence REAL,
        transcript_engine     TEXT,
        transcript_made_at    TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_voice_note_family
        ON voice_note(family_id, recorded_at DESC);
    """,
    """
    -- TASK-819. The ledger is searchable and exportable; the family's words or voice are
    -- encrypted in the file named by storage_key. The adapter publishes that file before
    -- committing this row and reconciles both sides on startup, so no half-seal is readable.
    CREATE TABLE IF NOT EXISTS future_inbox (
        id           TEXT PRIMARY KEY,
        family_id    TEXT NOT NULL REFERENCES family(id) ON DELETE CASCADE,
        child_id     TEXT NOT NULL,
        sealed_by    TEXT NOT NULL,
        opening_key  TEXT NOT NULL,
        care         TEXT NOT NULL,
        sealed_at    TEXT NOT NULL,
        ledger_json  TEXT NOT NULL,
        storage_key  TEXT NOT NULL UNIQUE,
        encrypted    INTEGER NOT NULL CHECK (encrypted = 1)
    );

    CREATE INDEX IF NOT EXISTS idx_future_inbox_family
        ON future_inbox(family_id, sealed_at);
    """,
)


@dataclass(frozen=True, slots=True)
class Rows:
    """A materialised query result.

    `execute` fetches inside the lock and hands back rows, never a live cursor. A cursor
    read after the lock is released can interleave with another thread's statement on the
    same connection, which is precisely the misuse this module exists to prevent.
    """

    rows: list[sqlite3.Row]
    rowcount: int
    lastrowid: int | None

    def fetchone(self) -> sqlite3.Row | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[sqlite3.Row]:
        return list(self.rows)

    def __iter__(self) -> Iterator[sqlite3.Row]:
        return iter(self.rows)


class GuardedConnection:
    """A SQLite connection that is safe to share across threads.

    Sync FastAPI endpoints run in a threadpool, so concurrent requests genuinely do reach
    one connection object at the same time. `check_same_thread=False` permits that; it
    does not make it correct. A re-entrant lock serialises access, and because it is
    re-entrant a `UnitOfWork` can hold it for a whole transaction without deadlocking the
    statements inside it.

    SQLite is a single-writer store anyway, so serialising costs a one-family product
    nothing and removes an entire class of intermittent corruption.
    """

    __slots__ = ("_raw", "lock")

    def __init__(self, raw: sqlite3.Connection) -> None:
        self._raw = raw
        self.lock = threading.RLock()

    def execute(self, sql: str, params: object = ()) -> Rows:
        with self.lock:
            cursor = self._raw.execute(sql, params)  # type: ignore[arg-type]
            return Rows(cursor.fetchall(), cursor.rowcount, cursor.lastrowid)

    def executescript(self, script: str) -> None:
        with self.lock:
            self._raw.executescript(script)

    def commit(self) -> None:
        with self.lock:
            self._raw.commit()

    def rollback(self) -> None:
        with self.lock:
            self._raw.rollback()

    def close(self) -> None:
        with self.lock:
            self._raw.close()

    @property
    def in_transaction(self) -> bool:
        return self._raw.in_transaction


def connect(path: str) -> GuardedConnection:
    """Open a connection with the settings a family archive deserves."""
    raw = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    raw.row_factory = sqlite3.Row
    connection = GuardedConnection(raw)
    connection.execute("PRAGMA journal_mode = WAL")  # survive a crash mid-write
    connection.execute("PRAGMA foreign_keys = ON")  # deletion must actually cascade
    connection.execute("PRAGMA synchronous = FULL")  # memories are not worth losing to fsync
    return connection


def migrate(connection: GuardedConnection) -> int:
    """Apply pending migrations. Idempotent, so running it on every boot is safe."""
    row = connection.execute("PRAGMA user_version").fetchone()
    current = int(row[0]) if row else 0
    for version, statements in enumerate(_MIGRATIONS, start=1):
        if version > current:
            connection.executescript(statements)
            connection.execute(f"PRAGMA user_version = {version}")
    return SCHEMA_VERSION
