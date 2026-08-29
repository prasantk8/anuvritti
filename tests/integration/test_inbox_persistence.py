"""TASK-819 — a Future Inbox seal is one durable fact, never two loose files."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from anuvritti.adapters.persistence.inbox import AtomicEncryptedFutureInboxStore
from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.application.ports import FutureInboxStore
from anuvritti.domain.inbox import (
    FutureMessage,
    MessageCare,
    OpeningKey,
    PresentedArtifact,
)
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, FutureMessageId, MemberId

NOW = datetime(2026, 8, 29, 8, 15, tzinfo=UTC)
FAMILY = FamilyId("fam-1")
CHILD = ChildId("chi-1")
PAPA = MemberId("mem-papa")
MESSAGE = FutureMessageId("inbox-1")
WORDS = "बेटा, तुम्हारी जिज्ञासा हमेशा तुम्हारी ताक़त रही है।"


def letter(text: str = WORDS) -> tuple[FutureMessage, PresentedArtifact]:
    message = FutureMessage.seal_written(
        message_id=MESSAGE,
        family_id=FAMILY,
        child_id=CHILD,
        sealed_by=PAPA,
        opening_key=OpeningKey.EIGHTEENTH_BIRTHDAY,
        care=MessageCare.ORDINARY,
        text=text,
        at=NOW,
    ).unwrap()
    return message, PresentedArtifact.written(text, message_id=MESSAGE)


def store(tmp_path: Path, db, *, key: str | None = None, fault=None):
    return AtomicEncryptedFutureInboxStore(
        root=tmp_path / "future-inbox",
        connection=db,
        encryption_key=key or Fernet.generate_key().decode(),
        fault=fault,
    )


class TestRoundTrip:
    def test_adapter_satisfies_the_atomic_store_port(self, tmp_path, db):
        assert isinstance(store(tmp_path, db), FutureInboxStore)

    def test_message_ledger_and_exact_artifact_return_together(self, tmp_path, db, seeded_family):
        inbox = store(tmp_path, db)
        message, artifact = letter()

        assert inbox.save(message, artifact).unwrap() == message
        restored = inbox.get(MESSAGE).unwrap()
        presented = inbox.get_artifact(MESSAGE).unwrap()

        assert restored == message
        assert presented.content == WORDS.encode("utf-8")
        assert restored.ledger.entry.verify(presented).unwrap() == WORDS.encode("utf-8")

    def test_plaintext_is_absent_from_sqlite_and_the_filesystem(self, tmp_path, db, seeded_family):
        inbox = store(tmp_path, db)
        message, artifact = letter()
        inbox.save(message, artifact).unwrap()

        row = db.execute(
            "SELECT ledger_json FROM future_inbox WHERE id = ?", (str(MESSAGE),)
        ).fetchone()
        assert row is not None
        assert WORDS not in row["ledger_json"]
        stored = b"".join(
            path.read_bytes() for path in (tmp_path / "future-inbox").rglob("*") if path.is_file()
        )
        assert WORDS.encode("utf-8") not in stored

    def test_a_different_family_key_cannot_read_the_artifact(self, tmp_path, db, seeded_family):
        original = store(tmp_path, db)
        message, artifact = letter()
        original.save(message, artifact).unwrap()

        intruder = store(tmp_path, db, key=Fernet.generate_key().decode())
        assert intruder.get_artifact(MESSAGE).unwrap_err().code is ErrorCode.PERMISSION_DENIED

    def test_an_artifact_that_does_not_match_the_ledger_is_never_written(
        self, tmp_path, db, seeded_family
    ):
        inbox = store(tmp_path, db)
        message, _ = letter()

        result = inbox.save(message, PresentedArtifact.written("replacement", message_id=MESSAGE))

        assert result.unwrap_err().code is ErrorCode.CONFLICT
        assert db.execute("SELECT * FROM future_inbox").fetchall() == []
        assert not list((tmp_path / "future-inbox").rglob("*.sealed"))

    def test_a_seal_is_immutable(self, tmp_path, db, seeded_family):
        inbox = store(tmp_path, db)
        message, artifact = letter()
        inbox.save(message, artifact).unwrap()
        assert inbox.save(message, artifact).unwrap_err().code is ErrorCode.CONFLICT

    def test_portable_ledger_and_family_listing_never_need_the_artifact(
        self, tmp_path, db, seeded_family
    ):
        inbox = store(tmp_path, db)
        message, artifact = letter()
        inbox.save(message, artifact).unwrap()

        assert inbox.ledger(MESSAGE).unwrap().to_dict() == message.ledger.to_dict()
        assert inbox.list_for_family(FAMILY).unwrap() == [message]
        assert inbox.list_for_family(FamilyId("fam-other")).unwrap() == []

    def test_unknown_seals_are_content_free_errors(self, tmp_path, db):
        inbox = store(tmp_path, db)
        unknown = FutureMessageId("inbox-unknown")
        assert inbox.get(unknown).unwrap_err().code is ErrorCode.MEDIA_NOT_FOUND
        assert inbox.get_artifact(unknown).unwrap_err().code is ErrorCode.MEDIA_NOT_FOUND

    def test_a_malformed_portable_ledger_is_refused(self, tmp_path, db, seeded_family):
        inbox = store(tmp_path, db)
        message, artifact = letter()
        inbox.save(message, artifact).unwrap()
        db.execute("UPDATE future_inbox SET ledger_json = '{broken' WHERE id = ?", (str(MESSAGE),))
        assert inbox.get(MESSAGE).unwrap_err().code is ErrorCode.CONFLICT

    def test_an_ordinary_io_failure_rolls_back_and_cleans_staging(
        self, tmp_path, db, seeded_family
    ):
        def fail(stage: str) -> None:
            if stage == "after_publish":
                raise OSError("disk refused the write")

        inbox = store(tmp_path, db, fault=fail)
        message, artifact = letter()
        assert inbox.save(message, artifact).unwrap_err().code is ErrorCode.CONFLICT
        assert db.execute("SELECT * FROM future_inbox").fetchall() == []
        assert not [path for path in (tmp_path / "future-inbox").rglob("*") if path.is_file()]


class SimulatedProcessDeath(BaseException):
    """Escapes ordinary adapter cleanup, as SIGKILL or power loss would."""


def standalone(tmp_path: Path):
    connection = connect(str(tmp_path / "archive.db"))
    migrate(connection)
    connection.execute(
        "INSERT INTO family (id, name, created_at) VALUES (?, ?, ?)",
        (str(FAMILY), "Our family", NOW.isoformat()),
    )
    return connection


@pytest.mark.parametrize("death_at", ["after_stage_fsync", "after_publish"])
def test_restart_recovers_every_crash_window_without_a_half_seal(tmp_path, death_at):
    db = standalone(tmp_path)

    def die(stage: str) -> None:
        if stage == death_at:
            raise SimulatedProcessDeath(stage)

    inbox = store(tmp_path, db, fault=die)
    message, artifact = letter()
    with pytest.raises(SimulatedProcessDeath):
        inbox.save(message, artifact)
    db.close()  # SQLite rolls back the uncommitted ledger, like process exit.

    reopened = standalone_existing(tmp_path)
    recovered = store(tmp_path, reopened)
    assert recovered.get(MESSAGE).is_err()
    assert reopened.execute("SELECT * FROM future_inbox").fetchall() == []
    assert not [path for path in (tmp_path / "future-inbox").rglob("*") if path.is_file()]
    reopened.close()


def standalone_existing(tmp_path: Path):
    connection = connect(str(tmp_path / "archive.db"))
    migrate(connection)
    return connection


def test_startup_reports_and_removes_staging_and_orphan_ciphertext(tmp_path):
    db = standalone(tmp_path)
    root = tmp_path / "future-inbox"
    staging = root / ".staging"
    staging.mkdir(parents=True)
    (staging / "seal-interrupted.tmp").write_bytes(b"private staging")
    (root / "unreferenced.sealed").write_bytes(b"orphan")

    inbox = store(tmp_path, db)

    assert inbox.last_recovery.staged_files_removed == 1
    assert inbox.last_recovery.orphan_files_removed == 1
    assert inbox.last_recovery.incomplete_ledgers_removed == 0
    assert not [path for path in root.rglob("*") if path.is_file()]
    db.close()


def test_restart_removes_a_ledger_whose_encrypted_artifact_was_lost(tmp_path):
    db = standalone(tmp_path)
    inbox = store(tmp_path, db)
    message, artifact = letter()
    inbox.save(message, artifact).unwrap()
    row = db.execute(
        "SELECT storage_key FROM future_inbox WHERE id = ?", (str(MESSAGE),)
    ).fetchone()
    assert row is not None
    (tmp_path / "future-inbox" / row["storage_key"]).unlink()
    db.close()

    reopened = standalone_existing(tmp_path)
    recovered = store(tmp_path, reopened)
    assert recovered.get(MESSAGE).is_err()
    assert reopened.execute("SELECT * FROM future_inbox").fetchall() == []
    reopened.close()


def test_family_erasure_removes_both_ledger_and_ciphertext(tmp_path, db, seeded_family):
    inbox = store(tmp_path, db)
    message, artifact = letter()
    inbox.save(message, artifact).unwrap()

    assert inbox.delete_for_family(FAMILY).unwrap() == 1
    assert inbox.get(MESSAGE).is_err()
    assert not [path for path in (tmp_path / "future-inbox").rglob("*") if path.is_file()]
