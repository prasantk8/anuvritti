"""TASK-214 - encrypted media store (PRD 44).

These bytes are a child's face and a family's voice. The tests assert the three things
that makes that acceptable: it is encrypted on disk, it can be proven intact, and it can
actually be destroyed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from anuvritti.adapters.media.filesystem import EncryptedFilesystemMediaStore
from anuvritti.adapters.persistence.sqlite import SqliteMediaCatalogue
from anuvritti.application.ports import MediaStore
from anuvritti.config.settings import DEFAULT_ALLOWED_MEDIA_TYPES
from anuvritti.domain.media import MediaKind
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import MediaId, SequentialIdGenerator
from tests.integration.conftest import FAMILY

NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
PHOTO = b"\xff\xd8\xff\xe0" + b"a happy face" * 40
KEY = Fernet.generate_key().decode()


def _store(tmp_path: Path, db, *, key: str | None = KEY, max_bytes: int = 1024 * 1024):
    return EncryptedFilesystemMediaStore(
        root=tmp_path / "media",
        catalogue=SqliteMediaCatalogue(db),
        ids=SequentialIdGenerator("med"),
        encryption_key=key,
        max_bytes=max_bytes,
        allowed_mime_types=DEFAULT_ALLOWED_MEDIA_TYPES,
    )


@pytest.fixture
def store(tmp_path, db):
    return _store(tmp_path, db)


class TestPortConformance:
    def test_it_satisfies_the_media_store_port(self, store):
        assert isinstance(store, MediaStore)


class TestRoundTrip:
    def test_bytes_come_back_exactly(self, store):
        media = store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        assert store.get(media.id).unwrap() == PHOTO

    def test_metadata_describes_the_file(self, store):
        media = store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        assert media.kind is MediaKind.IMAGE
        assert media.byte_size == len(PHOTO)
        assert media.mime_type == "image/jpeg"

    def test_audio_is_recognised_as_audio(self, store):
        media = store.put(FAMILY, content=b"ID3 voice", mime_type="audio/mpeg", at=NOW).unwrap()
        assert media.kind is MediaKind.AUDIO

    def test_a_charset_suffix_on_the_mime_type_is_tolerated(self, store):
        assert store.put(
            FAMILY, content=PHOTO, mime_type="image/jpeg; charset=binary", at=NOW
        ).is_ok()

    def test_describing_an_unknown_media_is_an_error(self, store):
        assert store.describe(MediaId("nope")).unwrap_err().code is ErrorCode.MEDIA_NOT_FOUND

    def test_getting_unknown_media_is_an_error(self, store):
        assert store.get(MediaId("nope")).unwrap_err().code is ErrorCode.MEDIA_NOT_FOUND


class TestEncryptionAtRest:
    def test_the_plaintext_never_appears_on_disk(self, tmp_path, store):
        """PRD 44 - encryption at rest is not optional."""
        store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        on_disk = b"".join(p.read_bytes() for p in (tmp_path / "media").rglob("*") if p.is_file())
        assert PHOTO not in on_disk
        assert b"a happy face" not in on_disk

    def test_the_record_states_that_it_is_encrypted(self, store):
        media = store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        assert media.encrypted is True

    def test_a_different_key_cannot_read_the_bytes(self, tmp_path, db, store):
        media = store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        intruder = _store(tmp_path, db, key=Fernet.generate_key().decode())
        assert intruder.get(media.id).unwrap_err().code is ErrorCode.MEDIA_NOT_FOUND

    def test_no_key_at_all_cannot_read_encrypted_bytes(self, tmp_path, db, store):
        media = store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        keyless = _store(tmp_path, db, key=None)
        assert keyless.get(media.id).is_err()

    def test_a_development_store_without_a_key_still_works(self, tmp_path, db):
        """Local development must not require key management to run the app."""
        plain = _store(tmp_path, db, key=None)
        media = plain.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        assert media.encrypted is False
        assert plain.get(media.id).unwrap() == PHOTO


class TestIntegrity:
    def test_tampered_bytes_are_detected_rather_than_returned(self, tmp_path, db):
        """A silently corrupted memory is worse than a missing one."""
        plain = _store(tmp_path, db, key=None)
        media = plain.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        (tmp_path / "media" / media.storage_key).write_bytes(b"someone else's photo")
        assert plain.get(media.id).unwrap_err().code is ErrorCode.CONFLICT

    def test_bytes_missing_from_disk_are_reported_clearly(self, tmp_path, store):
        media = store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        (tmp_path / "media" / media.storage_key).unlink()
        assert store.get(media.id).unwrap_err().code is ErrorCode.MEDIA_NOT_FOUND

    def test_identical_content_is_stored_once(self, tmp_path, store):
        first = store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        second = store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        assert first.id != second.id
        assert first.storage_key == second.storage_key
        files = [p for p in (tmp_path / "media").rglob("*") if p.is_file()]
        assert len(files) == 1

    def test_both_records_still_read_correctly_after_deduplication(self, store):
        first = store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        second = store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        assert store.get(first.id).unwrap() == store.get(second.id).unwrap() == PHOTO


class TestLimits:
    def test_empty_content_is_rejected(self, store):
        err = store.put(FAMILY, content=b"", mime_type="image/jpeg", at=NOW).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_oversized_content_is_rejected(self, tmp_path, db):
        small = _store(tmp_path, db, max_bytes=16)
        err = small.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap_err()
        assert err.code is ErrorCode.MEDIA_TOO_LARGE
        assert err.details["limit"] == 16

    @pytest.mark.parametrize(
        "mime_type", ["text/html", "application/pdf", "application/x-executable", "video/mp4"]
    )
    def test_only_allow_listed_media_types_are_accepted(self, store, mime_type):
        """An allow-list, not a deny-list. HTML in a family archive is an attack surface."""
        err = store.put(FAMILY, content=PHOTO, mime_type=mime_type, at=NOW).unwrap_err()
        assert err.code is ErrorCode.MEDIA_KIND_UNSUPPORTED

    def test_nothing_is_written_when_the_type_is_rejected(self, tmp_path, store):
        store.put(FAMILY, content=PHOTO, mime_type="text/html", at=NOW)
        assert not [p for p in (tmp_path / "media").rglob("*") if p.is_file()]


class TestErasure:
    def test_deleting_a_family_removes_the_bytes_from_disk(self, tmp_path, store):
        """PRD 44 - a "delete everything" you cannot execute is not a promise."""
        store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        store.put(FAMILY, content=b"ID3 voice", mime_type="audio/mpeg", at=NOW).unwrap()

        assert store.delete_for_family(FAMILY).unwrap() == 2
        assert not [p for p in (tmp_path / "media").rglob("*") if p.is_file()]

    def test_deleting_removes_the_catalogue_entries(self, store):
        media = store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        store.delete_for_family(FAMILY)
        assert store.describe(media.id).is_err()

    def test_deleting_an_empty_family_is_harmless(self, store):
        assert store.delete_for_family(FAMILY).unwrap() == 0

    def test_deletion_is_idempotent(self, store):
        store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        store.delete_for_family(FAMILY)
        assert store.delete_for_family(FAMILY).unwrap() == 0

    def test_another_familys_media_is_untouched(self, tmp_path, store):
        from anuvritti.shared.identity import FamilyId

        other = FamilyId("fam-2")
        store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        theirs = store.put(other, content=b"ID3 other", mime_type="audio/mpeg", at=NOW).unwrap()

        store.delete_for_family(FAMILY)
        assert store.get(theirs.id).unwrap() == b"ID3 other"


class TestListing:
    def test_listing_returns_a_families_media(self, store):
        store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        store.put(FAMILY, content=b"ID3 voice", mime_type="audio/mpeg", at=NOW).unwrap()
        assert len(store.list_for_family(FAMILY).unwrap()) == 2

    def test_listing_is_scoped_to_one_family(self, store):
        from anuvritti.shared.identity import FamilyId

        store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        assert store.list_for_family(FamilyId("fam-other")).unwrap() == []

    def test_the_manifest_never_contains_the_bytes(self, store):
        """An export manifest is an index, not a second copy."""
        store.put(FAMILY, content=PHOTO, mime_type="image/jpeg", at=NOW).unwrap()
        manifest = [m.to_dict() for m in store.list_for_family(FAMILY).unwrap()]
        assert "content" not in manifest[0]
        assert PHOTO not in str(manifest).encode()
