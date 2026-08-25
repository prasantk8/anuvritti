"""SQLite repositories (ADR-0003).

One file per family, owned by the family. That is the strongest available reading of the
local-first ambition in PRD 44, and it makes "export everything" and "delete everything"
tractable rather than aspirational.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from types import TracebackType

from anuvritti.adapters.persistence.mapping import (
    row_to_little_thing,
    row_to_media,
    row_to_moment,
    row_to_right_now,
    row_to_spark,
    rows_to_family,
    spark_to_row,
)
from anuvritti.adapters.persistence.schema import GuardedConnection
from anuvritti.domain.access import Device, PairingRequest
from anuvritti.domain.events import DomainEvent
from anuvritti.domain.family import Family
from anuvritti.domain.media import MediaObject
from anuvritti.domain.moment import Moment
from anuvritti.domain.presence import LittleThing, RightNowSnapshot
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import IntentType, SparkStatus
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import (
    ChildId,
    DeviceId,
    FamilyId,
    MediaId,
    MemberId,
    MomentId,
    SparkId,
)
from anuvritti.shared.result import Err, Ok, Result


class SqliteUnitOfWork:
    """A transaction boundary. A family archive is never left half-written."""

    def __init__(self, connection: GuardedConnection) -> None:
        self._connection = connection
        self._depth = 0

    def __enter__(self) -> SqliteUnitOfWork:
        if self._depth == 0:
            self._connection.execute("BEGIN")
        self._depth += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        self._depth -= 1
        if self._depth == 0 and self._connection.in_transaction:
            if exc_type is not None:
                self._connection.rollback()
            else:
                self._connection.commit()
        return None

    def commit(self) -> None:
        if self._depth <= 1 and self._connection.in_transaction:
            self._connection.commit()

    def rollback(self) -> None:
        if self._connection.in_transaction:
            self._connection.rollback()


class SqliteFamilyRepository:
    def __init__(self, connection: GuardedConnection) -> None:
        self._db = connection

    def count(self) -> int:
        """How many families this box holds. A production box closes its door after one."""
        row = self._db.execute("SELECT COUNT(*) AS n FROM family").fetchone()
        return int(row["n"]) if row else 0

    def get(self, family_id: FamilyId) -> Result[Family, DomainError]:
        row = self._db.execute("SELECT * FROM family WHERE id = ?", (str(family_id),)).fetchone()
        if row is None:
            return Err(DomainError(ErrorCode.FAMILY_NOT_FOUND, f"no family {family_id}"))
        members = self._db.execute(
            "SELECT * FROM member WHERE family_id = ? ORDER BY rowid", (str(family_id),)
        ).fetchall()
        children = self._db.execute(
            "SELECT * FROM child_profile WHERE family_id = ? ORDER BY rowid", (str(family_id),)
        ).fetchall()
        return Ok(rows_to_family(row, list(members), list(children)))

    def save(self, family: Family) -> Result[Family, DomainError]:
        self._db.execute(
            "INSERT INTO family (id, name, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
            (str(family.id), family.name, family.created_at.isoformat()),
        )
        for member in family.members:
            self._db.execute(
                "INSERT INTO member (id, family_id, display_name, role) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET display_name = excluded.display_name, "
                "role = excluded.role",
                (str(member.id), str(family.id), member.display_name, member.role.value),
            )
        for child in family.children:
            self._db.execute(
                "INSERT INTO child_profile (id, family_id, member_id, display_name, date_of_birth) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "display_name = excluded.display_name, date_of_birth = excluded.date_of_birth",
                (
                    str(child.id),
                    str(family.id),
                    str(child.member_id),
                    child.display_name,
                    child.date_of_birth.isoformat(),
                ),
            )
        return Ok(family)

    def delete(self, family_id: FamilyId) -> Result[int, DomainError]:
        cursor = self._db.execute("DELETE FROM family WHERE id = ?", (str(family_id),))
        return Ok(cursor.rowcount)


_SPARK_COLUMNS = (
    "id, family_id, owner_id, subject_child_id, title, note, "
    "source_kind, source_url, source_creator, source_title, source_text, source_media_id, "
    "intent_value, intent_source, intent_confidence, intent_overridden, "
    "category_value, category_source, category_confidence, category_overridden, "
    "age_min, age_max, age_source, age_confidence, age_overridden, "
    "tags_json, why_text, why_voice_media_id, why_recorded_at, "
    "status, visibility, suggested_count, last_suggested_at, snoozed_until, "
    "created_at, updated_at"
)


class SqliteSparkRepository:
    def __init__(self, connection: GuardedConnection) -> None:
        self._db = connection

    def get(self, spark_id: SparkId) -> Result[Spark, DomainError]:
        row = self._db.execute("SELECT * FROM spark WHERE id = ?", (str(spark_id),)).fetchone()
        if row is None:
            return Err(DomainError(ErrorCode.SPARK_NOT_FOUND, f"no spark {spark_id}"))
        return Ok(row_to_spark(row))

    def save(self, spark: Spark) -> Result[Spark, DomainError]:
        row = spark_to_row(spark)
        # Column names come from `spark_to_row`, which is code in this repository - no
        # caller can introduce one. Every *value* is bound through named placeholders.
        columns = list(row.keys())
        placeholders = ", ".join(f":{name}" for name in columns)
        updates = ", ".join(f"{name} = excluded.{name}" for name in columns if name != "id")
        self._db.execute(
            f"INSERT INTO spark ({', '.join(columns)}) VALUES ({placeholders}) "  # noqa: S608  # nosec B608
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            row,
        )
        return Ok(spark)

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[Spark], DomainError]:
        rows = self._db.execute(
            "SELECT * FROM spark WHERE family_id = ? ORDER BY created_at DESC", (str(family_id),)
        ).fetchall()
        return Ok([row_to_spark(r) for r in rows])

    def search(
        self,
        family_id: FamilyId,
        *,
        text: str | None = None,
        intent: IntentType | None = None,
        child_id: ChildId | None = None,
        age_years: int | None = None,
        status: SparkStatus | None = None,
        limit: int = 25,
    ) -> Result[Sequence[Spark], DomainError]:
        clauses = ["family_id = ?"]
        params: list[object] = [str(family_id)]

        if text:
            # PRD 48 F5 - the parent's own words are part of the index, alongside what
            # the engine inferred. Neither alone is enough to find a half-remembered thing.
            needle = f"%{text.lower()}%"
            clauses.append(
                "(LOWER(title) LIKE ? OR LOWER(COALESCE(note, '')) LIKE ? "
                "OR LOWER(COALESCE(source_text, '')) LIKE ? "
                "OR LOWER(COALESCE(why_text, '')) LIKE ? "
                "OR LOWER(category_value) LIKE ? OR LOWER(tags_json) LIKE ?)"
            )
            params.extend([needle] * 6)
        if intent:
            clauses.append("intent_value = ?")
            params.append(intent.value)
        if child_id:
            clauses.append("subject_child_id = ?")
            params.append(str(child_id))
        if status:
            clauses.append("status = ?")
            params.append(status.value)
        if age_years is not None:
            # A Spark with no age range is never excluded - absence of a guess is not a
            # statement that it is unsuitable.
            clauses.append("(age_min IS NULL OR (? BETWEEN age_min AND age_max))")
            params.append(age_years)

        params.append(limit)
        # `clauses` holds only literal strings written above; every user-supplied value
        # went into `params` as a bound `?`. Covered by the SQL-injection test in
        # tests/integration/test_sqlite_repositories.py.
        rows = self._db.execute(
            f"SELECT * FROM spark WHERE {' AND '.join(clauses)} "  # noqa: S608  # nosec B608
            "ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return Ok([row_to_spark(r) for r in rows])

    def list_returnable(self, family_id: FamilyId) -> Result[Sequence[Spark], DomainError]:
        returnable = [s.value for s in SparkStatus if s.is_returnable]
        # `placeholders` is a run of literal "?" - the statuses themselves are bound.
        placeholders = ", ".join("?" for _ in returnable)
        rows = self._db.execute(
            f"SELECT * FROM spark WHERE family_id = ? AND status IN ({placeholders}) "  # noqa: S608  # nosec B608
            "ORDER BY created_at ASC",
            (str(family_id), *returnable),
        ).fetchall()
        return Ok([row_to_spark(r) for r in rows])

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        cursor = self._db.execute("DELETE FROM spark WHERE family_id = ?", (str(family_id),))
        return Ok(cursor.rowcount)


class SqliteMomentRepository:
    def __init__(self, connection: GuardedConnection) -> None:
        self._db = connection

    def get(self, moment_id: MomentId) -> Result[Moment, DomainError]:
        row = self._db.execute("SELECT * FROM moment WHERE id = ?", (str(moment_id),)).fetchone()
        if row is None:
            return Err(DomainError(ErrorCode.MOMENT_NOT_FOUND, f"no moment {moment_id}"))
        return Ok(row_to_moment(row))

    def save(self, moment: Moment) -> Result[Moment, DomainError]:
        try:
            self._db.execute(
                "INSERT INTO moment (id, family_id, spark_id, happened_on, reflection, "
                "photo_media_id, audio_media_id, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "reflection = excluded.reflection, photo_media_id = excluded.photo_media_id, "
                "audio_media_id = excluded.audio_media_id, happened_on = excluded.happened_on",
                (
                    str(moment.id),
                    str(moment.family_id),
                    str(moment.spark_id),
                    moment.happened_on.isoformat(),
                    moment.reflection,
                    moment.photo_media_id,
                    moment.audio_media_id,
                    str(moment.created_by),
                    moment.created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    "this spark already became a moment",
                    {"spark_id": str(moment.spark_id), "detail": str(exc)},
                )
            )
        return Ok(moment)

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[Moment], DomainError]:
        rows = self._db.execute(
            "SELECT * FROM moment WHERE family_id = ? ORDER BY happened_on DESC", (str(family_id),)
        ).fetchall()
        return Ok([row_to_moment(r) for r in rows])

    def find_by_spark(self, spark_id: SparkId) -> Result[Moment | None, DomainError]:
        row = self._db.execute(
            "SELECT * FROM moment WHERE spark_id = ?", (str(spark_id),)
        ).fetchone()
        return Ok(row_to_moment(row) if row else None)

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        cursor = self._db.execute("DELETE FROM moment WHERE family_id = ?", (str(family_id),))
        return Ok(cursor.rowcount)


class SqliteLittleThingRepository:
    def __init__(self, connection: GuardedConnection) -> None:
        self._db = connection

    def save(self, little_thing: LittleThing) -> Result[LittleThing, DomainError]:
        self._db.execute(
            "INSERT INTO little_thing (id, family_id, author_id, subject_child_id, text, "
            "audio_media_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET text = excluded.text",
            (
                str(little_thing.id),
                str(little_thing.family_id),
                str(little_thing.author_id),
                str(little_thing.subject_child_id) if little_thing.subject_child_id else None,
                little_thing.text,
                little_thing.audio_media_id,
                little_thing.created_at.isoformat(),
            ),
        )
        return Ok(little_thing)

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[LittleThing], DomainError]:
        rows = self._db.execute(
            "SELECT * FROM little_thing WHERE family_id = ? ORDER BY created_at DESC",
            (str(family_id),),
        ).fetchall()
        return Ok([row_to_little_thing(r) for r in rows])

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        cursor = self._db.execute("DELETE FROM little_thing WHERE family_id = ?", (str(family_id),))
        return Ok(cursor.rowcount)


class SqliteRightNowRepository:
    def __init__(self, connection: GuardedConnection) -> None:
        self._db = connection

    def save(self, snapshot: RightNowSnapshot) -> Result[RightNowSnapshot, DomainError]:
        self._db.execute(
            "INSERT INTO right_now (id, family_id, child_id, prompt, answer, captured_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET answer = excluded.answer",
            (
                str(snapshot.id),
                str(snapshot.family_id),
                str(snapshot.child_id),
                snapshot.prompt,
                snapshot.answer,
                snapshot.captured_at.isoformat(),
            ),
        )
        return Ok(snapshot)

    def list_for_family(
        self, family_id: FamilyId
    ) -> Result[Sequence[RightNowSnapshot], DomainError]:
        rows = self._db.execute(
            "SELECT * FROM right_now WHERE family_id = ? ORDER BY captured_at DESC",
            (str(family_id),),
        ).fetchall()
        return Ok([row_to_right_now(r) for r in rows])

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        cursor = self._db.execute("DELETE FROM right_now WHERE family_id = ?", (str(family_id),))
        return Ok(cursor.rowcount)


class SqliteMediaCatalogue:
    """Metadata only. The bytes live in the MediaStore adapter."""

    def __init__(self, connection: GuardedConnection) -> None:
        self._db = connection

    def record(self, media: MediaObject) -> None:
        self._db.execute(
            "INSERT INTO media (id, family_id, kind, mime_type, byte_size, content_hash, "
            "storage_key, encrypted, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO NOTHING",
            (
                str(media.id),
                str(media.family_id),
                media.kind.value,
                media.mime_type,
                media.byte_size,
                media.content_hash,
                media.storage_key,
                int(media.encrypted),
                media.created_at.isoformat(),
            ),
        )

    def find(self, media_id: MediaId) -> MediaObject | None:
        row = self._db.execute("SELECT * FROM media WHERE id = ?", (str(media_id),)).fetchone()
        return row_to_media(row) if row else None

    def list_for_family(self, family_id: FamilyId) -> list[MediaObject]:
        rows = self._db.execute(
            "SELECT * FROM media WHERE family_id = ?", (str(family_id),)
        ).fetchall()
        return [row_to_media(r) for r in rows]

    def delete_for_family(self, family_id: FamilyId) -> int:
        cursor = self._db.execute("DELETE FROM media WHERE family_id = ?", (str(family_id),))
        return cursor.rowcount


class SqliteEventPublisher:
    """Append-only audit trail (PRD 44). Structural payloads only - never content."""

    def __init__(self, connection: GuardedConnection) -> None:
        self._db = connection

    def publish(self, events: Sequence[DomainEvent], *, family_id: FamilyId) -> None:
        for event in events:
            self._db.execute(
                "INSERT INTO domain_event (family_id, aggregate_id, name, payload_json, "
                "occurred_at) VALUES (?, ?, ?, ?, ?)",
                (
                    str(family_id),
                    event.aggregate_id,
                    event.name,
                    json.dumps(event.payload(), default=str),
                    event.occurred_at.isoformat(),
                ),
            )

    def list_for_family(self, family_id: FamilyId) -> Sequence[DomainEvent]:
        rows = self._db.execute(
            "SELECT * FROM domain_event WHERE family_id = ? ORDER BY id", (str(family_id),)
        ).fetchall()
        return [
            DomainEvent(
                aggregate_id=r["aggregate_id"], occurred_at=datetime.fromisoformat(r["occurred_at"])
            )
            for r in rows
        ]

    def raw_for_family(self, family_id: FamilyId) -> list[dict[str, object]]:
        """The audit trail as stored, for export (PRD 44)."""
        rows = self._db.execute(
            "SELECT * FROM domain_event WHERE family_id = ? ORDER BY id", (str(family_id),)
        ).fetchall()
        return [
            {
                "name": r["name"],
                "aggregate_id": r["aggregate_id"],
                "occurred_at": r["occurred_at"],
                "payload": json.loads(r["payload_json"]),
            }
            for r in rows
        ]

    def delete_for_family(self, family_id: FamilyId) -> int:
        cursor = self._db.execute("DELETE FROM domain_event WHERE family_id = ?", (str(family_id),))
        return cursor.rowcount


class SqliteDeviceRepository:
    """Paired devices (TASK-511).

    Every lookup is by fingerprint. The plaintext token is never a query parameter, so it
    cannot reach a slow-query log, an EXPLAIN, or a `.dump` of the archive.
    """

    def __init__(self, connection: GuardedConnection) -> None:
        self._db = connection

    def get(self, device_id: DeviceId) -> Result[Device, DomainError]:
        row = self._db.execute("SELECT * FROM device WHERE id = ?", (str(device_id),)).fetchone()
        if row is None:
            return Err(DomainError(ErrorCode.MEMBER_NOT_FOUND, "no such device"))
        return Ok(_row_to_device(row))

    def save(self, device: Device) -> Result[Device, DomainError]:
        self._db.execute(
            "INSERT INTO device (id, family_id, member_id, display_name, token_fingerprint, "
            "created_at, last_seen_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET display_name = excluded.display_name, "
            "last_seen_at = excluded.last_seen_at, revoked_at = excluded.revoked_at",
            (
                str(device.id),
                str(device.family_id),
                str(device.member_id),
                device.display_name,
                device.token_fingerprint,
                device.created_at.isoformat(),
                device.last_seen_at.isoformat() if device.last_seen_at else None,
                device.revoked_at.isoformat() if device.revoked_at else None,
            ),
        )
        return Ok(device)

    def find_by_fingerprint(self, fingerprint: str) -> Result[Device | None, DomainError]:
        row = self._db.execute(
            "SELECT * FROM device WHERE token_fingerprint = ?", (fingerprint,)
        ).fetchone()
        return Ok(_row_to_device(row) if row is not None else None)

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[Device], DomainError]:
        rows = self._db.execute(
            "SELECT * FROM device WHERE family_id = ? ORDER BY created_at",
            (str(family_id),),
        ).fetchall()
        return Ok([_row_to_device(r) for r in rows])

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        cursor = self._db.execute("DELETE FROM device WHERE family_id = ?", (str(family_id),))
        return Ok(cursor.rowcount)


class SqlitePairingRepository:
    """Open codes and the attempt ledger."""

    def __init__(self, connection: GuardedConnection) -> None:
        self._db = connection

    def save(self, request: PairingRequest) -> Result[PairingRequest, DomainError]:
        self._db.execute(
            "INSERT INTO pairing_request (code_fingerprint, family_id, member_id, created_at, "
            "expires_at, claimed_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(code_fingerprint) DO UPDATE SET claimed_at = excluded.claimed_at",
            (
                request.code_fingerprint,
                str(request.family_id),
                str(request.member_id),
                request.created_at.isoformat(),
                request.expires_at.isoformat(),
                request.claimed_at.isoformat() if request.claimed_at else None,
            ),
        )
        return Ok(request)

    def find_by_fingerprint(self, fingerprint: str) -> Result[PairingRequest | None, DomainError]:
        row = self._db.execute(
            "SELECT * FROM pairing_request WHERE code_fingerprint = ?", (fingerprint,)
        ).fetchone()
        if row is None:
            return Ok(None)
        return Ok(
            PairingRequest(
                code_fingerprint=row["code_fingerprint"],
                family_id=FamilyId(row["family_id"]),
                member_id=MemberId(row["member_id"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                expires_at=datetime.fromisoformat(row["expires_at"]),
                claimed_at=(
                    datetime.fromisoformat(row["claimed_at"]) if row["claimed_at"] else None
                ),
            )
        )

    def record_attempt(self, *, succeeded: bool, at: datetime) -> None:
        self._db.execute(
            "INSERT INTO pairing_attempt (succeeded, occurred_at) VALUES (?, ?)",
            (1 if succeeded else 0, at.isoformat()),
        )

    def failures_since(self, since: datetime) -> int:
        row = self._db.execute(
            "SELECT COUNT(*) AS n FROM pairing_attempt WHERE succeeded = 0 AND occurred_at >= ?",
            (since.isoformat(),),
        ).fetchone()
        return int(row["n"]) if row else 0

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        cursor = self._db.execute(
            "DELETE FROM pairing_request WHERE family_id = ?", (str(family_id),)
        )
        return Ok(cursor.rowcount)


class SqliteIdempotencyStore:
    """What a replayed capture is answered from (TASK-509).

    Scoped by family as well as key, so one family's key can never surface another family's
    response - the same isolation rule the token enforces, applied to the cache in front of it.
    """

    def __init__(self, connection: GuardedConnection) -> None:
        self._db = connection

    def recall(
        self, key: str, *, family_id: FamilyId
    ) -> Result[tuple[int, str, str] | None, DomainError]:
        row = self._db.execute(
            "SELECT status_code, response_json, request_fingerprint FROM idempotency "
            "WHERE key = ? AND family_id = ?",
            (key, str(family_id)),
        ).fetchone()
        if row is None:
            return Ok(None)
        return Ok((int(row["status_code"]), row["response_json"], row["request_fingerprint"]))

    def remember(
        self,
        key: str,
        *,
        family_id: FamilyId,
        request_fingerprint: str,
        status_code: int,
        response_json: str,
        at: datetime,
    ) -> Result[None, DomainError]:
        self._db.execute(
            "INSERT INTO idempotency (key, family_id, request_fingerprint, status_code, "
            "response_json, created_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(key, family_id) DO NOTHING",
            (key, str(family_id), request_fingerprint, status_code, response_json, at.isoformat()),
        )
        return Ok(None)

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        cursor = self._db.execute("DELETE FROM idempotency WHERE family_id = ?", (str(family_id),))
        return Ok(cursor.rowcount)


def _row_to_device(row: sqlite3.Row) -> Device:
    return Device(
        id=DeviceId(row["id"]),
        family_id=FamilyId(row["family_id"]),
        member_id=MemberId(row["member_id"]),
        display_name=row["display_name"],
        token_fingerprint=row["token_fingerprint"],
        created_at=datetime.fromisoformat(row["created_at"]),
        last_seen_at=datetime.fromisoformat(row["last_seen_at"]) if row["last_seen_at"] else None,
        revoked_at=datetime.fromisoformat(row["revoked_at"]) if row["revoked_at"] else None,
    )
