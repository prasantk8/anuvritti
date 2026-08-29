"""Atomic encrypted persistence for the Future Inbox (PRD 20, 44 and 47)."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from anuvritti.adapters.persistence.schema import GuardedConnection
from anuvritti.domain.inbox import (
    ArtifactKind,
    FutureMessage,
    MessageCare,
    OpeningKey,
    PresentedArtifact,
    SealedArtifact,
    SealLedger,
)
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, FutureMessageId, MemberId
from anuvritti.shared.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    staged_files_removed: int = 0
    orphan_files_removed: int = 0
    incomplete_ledgers_removed: int = 0


class AtomicEncryptedFutureInboxStore:
    """A SQLite ledger and encrypted file published as one recoverable seal.

    SQLite cannot enlist a filesystem rename in its transaction. The safe ordering is:
    fsync a private staging file, begin SQLite, publish the file atomically, insert the
    ledger, commit. A process death can then leave only staging or an unreferenced sealed
    file; startup recovery removes both. Publishing the file before committing the row
    means a committed ledger can never point at bytes that were not already durable.
    """

    def __init__(
        self,
        *,
        root: Path,
        connection: GuardedConnection,
        encryption_key: str,
        fault: Callable[[str], None] | None = None,
    ) -> None:
        self._root = root
        self._staging = root / ".staging"
        self._db = connection
        self._fernet = Fernet(encryption_key.encode("ascii"))
        self._fault = fault or (lambda _stage: None)
        self._staging.mkdir(parents=True, exist_ok=True)
        self.last_recovery = self.recover()

    def save(
        self, message: FutureMessage, artifact: PresentedArtifact
    ) -> Result[FutureMessage, DomainError]:
        verified = message.ledger.entry.verify(artifact)
        if isinstance(verified, Err):
            return verified
        storage_key = self._storage_key(message)
        final = self._root / storage_key
        final.parent.mkdir(parents=True, exist_ok=True)
        ciphertext = self._fernet.encrypt(verified.value)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="seal-", suffix=".tmp", dir=self._staging
        )
        temporary = Path(temporary_name)
        published = False
        try:
            with os.fdopen(descriptor, "wb") as staged:
                staged.write(ciphertext)
                staged.flush()
                os.fsync(staged.fileno())
            self._fault("after_stage_fsync")
            with self._db.lock:
                self._db.execute("BEGIN IMMEDIATE")
                if self._db.execute(
                    "SELECT 1 FROM future_inbox WHERE id = ?", (str(message.id),)
                ).fetchone():
                    self._db.rollback()
                    temporary.unlink(missing_ok=True)
                    return Err(
                        DomainError(
                            ErrorCode.CONFLICT,
                            "a Future Inbox seal is immutable once stored",
                            {"message_id": str(message.id)},
                        )
                    )
                temporary.replace(final)
                published = True
                self._fsync_directory(final.parent)
                self._fault("after_publish")
                self._insert(message, storage_key)
                self._db.commit()
            return Ok(message)
        except (OSError, sqlite3.Error, ValueError) as exc:
            if self._db.in_transaction:
                self._db.rollback()
            temporary.unlink(missing_ok=True)
            if published:
                final.unlink(missing_ok=True)
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    "the Future Inbox seal could not be committed atomically",
                    {"reason": type(exc).__name__},
                )
            )

    def get(self, message_id: FutureMessageId) -> Result[FutureMessage, DomainError]:
        row = self._db.execute(
            "SELECT * FROM future_inbox WHERE id = ?", (str(message_id),)
        ).fetchone()
        if row is None:
            return self._not_found(message_id)
        try:
            return Ok(self._message_from_row(row))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    "the Future Inbox ledger is not a valid portable seal",
                    {"message_id": str(message_id)},
                )
            )

    def get_artifact(self, message_id: FutureMessageId) -> Result[PresentedArtifact, DomainError]:
        message_result = self.get(message_id)
        if isinstance(message_result, Err):
            return message_result
        row = self._db.execute(
            "SELECT storage_key FROM future_inbox WHERE id = ?", (str(message_id),)
        ).fetchone()
        if row is None:
            return self._not_found(message_id)
        path = self._root / str(row["storage_key"])
        try:
            content = self._fernet.decrypt(path.read_bytes())
        except InvalidToken:
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    "the family key cannot open this Future Inbox artifact",
                    {"message_id": str(message_id)},
                )
            )
        except OSError:
            return self._not_found(message_id)
        entry = message_result.value.ledger.entry
        presented = PresentedArtifact(entry.kind, entry.source_id, content)
        verified = entry.verify(presented)
        if isinstance(verified, Err):
            return verified
        return Ok(presented)

    def ledger(self, message_id: FutureMessageId) -> Result[SealLedger, DomainError]:
        message = self.get(message_id)
        if isinstance(message, Err):
            return message
        return Ok(message.value.ledger)

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[FutureMessage], DomainError]:
        rows = self._db.execute(
            "SELECT * FROM future_inbox WHERE family_id = ? ORDER BY sealed_at",
            (str(family_id),),
        ).fetchall()
        messages: list[FutureMessage] = []
        try:
            messages.extend(self._message_from_row(row) for row in rows)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return Err(DomainError(ErrorCode.CONFLICT, "a Future Inbox ledger is invalid"))
        return Ok(messages)

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        with self._db.lock:
            self._db.execute("BEGIN IMMEDIATE")
            rows = self._db.execute(
                "SELECT storage_key FROM future_inbox WHERE family_id = ?", (str(family_id),)
            ).fetchall()
            for row in rows:
                (self._root / str(row["storage_key"])).unlink(missing_ok=True)
            removed = self._db.execute(
                "DELETE FROM future_inbox WHERE family_id = ?", (str(family_id),)
            ).rowcount
            self._db.commit()
        self._prune_empty_directories()
        return Ok(removed)

    def recover(self) -> RecoveryReport:
        staged = 0
        for path in self._staging.glob("seal-*.tmp"):
            path.unlink(missing_ok=True)
            staged += 1
        with self._db.lock:
            rows = self._db.execute("SELECT id, storage_key FROM future_inbox").fetchall()
            missing = [row for row in rows if not (self._root / str(row["storage_key"])).is_file()]
            if missing:
                self._db.execute("BEGIN IMMEDIATE")
                for row in missing:
                    self._db.execute("DELETE FROM future_inbox WHERE id = ?", (row["id"],))
                self._db.commit()
            referenced = {
                str(row["storage_key"])
                for row in self._db.execute("SELECT storage_key FROM future_inbox").fetchall()
            }
        orphaned = 0
        for path in self._root.rglob("*.sealed"):
            if str(path.relative_to(self._root)) not in referenced:
                path.unlink(missing_ok=True)
                orphaned += 1
        self._prune_empty_directories()
        return RecoveryReport(staged, orphaned, len(missing))

    def _insert(self, message: FutureMessage, storage_key: str) -> None:
        self._db.execute(
            "INSERT INTO future_inbox (id, family_id, child_id, sealed_by, opening_key, care, "
            "sealed_at, ledger_json, storage_key, encrypted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (
                str(message.id),
                str(message.family_id),
                str(message.child_id),
                str(message.sealed_by),
                message.opening_key.value,
                message.care.value,
                message.sealed_at.isoformat(),
                json.dumps(message.ledger.to_dict(), sort_keys=True, separators=(",", ":")),
                storage_key,
            ),
        )

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> FutureMessage:
        raw = json.loads(str(row["ledger_json"]))
        entries = raw["entries"]
        if raw.get("schema") != "anuvritti.future-inbox-provenance.v1" or len(entries) != 1:
            raise ValueError("unsupported ledger")
        entry = entries[0]
        sealed_at = datetime.fromisoformat(str(row["sealed_at"]))
        ledger = SealLedger(
            message_id=FutureMessageId(str(raw["message_id"])),
            sealed_at=datetime.fromisoformat(str(raw["sealed_at"])),
            entries=(
                SealedArtifact(
                    kind=ArtifactKind(str(entry["kind"])),
                    source_id=str(entry["source_id"]),
                    content_hash=str(entry["content_hash"]),
                    byte_size=int(entry["byte_size"]),
                ),
            ),
        )
        return FutureMessage(
            id=FutureMessageId(str(row["id"])),
            family_id=FamilyId(str(row["family_id"])),
            child_id=ChildId(str(row["child_id"])),
            sealed_by=MemberId(str(row["sealed_by"])),
            opening_key=OpeningKey(str(row["opening_key"])),
            care=MessageCare(str(row["care"])),
            sealed_at=sealed_at,
            ledger=ledger,
        )

    @staticmethod
    def _storage_key(message: FutureMessage) -> str:
        family = hashlib.sha256(str(message.family_id).encode()).hexdigest()[:16]
        seal = hashlib.sha256(str(message.id).encode()).hexdigest()
        return f"{family}/{seal}.sealed"

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _prune_empty_directories(self) -> None:
        for path in sorted(self._root.rglob("*"), reverse=True):
            if path.is_dir() and path != self._staging:
                with suppress(OSError):
                    path.rmdir()

    @staticmethod
    def _not_found(message_id: FutureMessageId) -> Err[DomainError]:
        return Err(
            DomainError(
                ErrorCode.MEDIA_NOT_FOUND,
                "the Future Inbox seal does not exist",
                {"message_id": str(message_id)},
            )
        )
