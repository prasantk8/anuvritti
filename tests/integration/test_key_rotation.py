"""TASK-1107 - Zero-Downtime Key Rotation & Media Re-wrapping (HARDENING 5.5, PRD 44).

Verifies that:
1. Media encrypted under an older key remains readable after key rotation.
2. New media is encrypted with the updated primary key.
3: Media re-wrapping (store.rewrap_all() & rotate_keys.py) updates ciphertexts to active key.
4: Once re-wrapped, historical keys can be safely retired.
5: Operates on real migrated database schema.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet
from scripts.rotate_keys import rotate_media_directory

from anuvritti.adapters.media.filesystem import EncryptedFilesystemMediaStore, rewrap_directory
from anuvritti.adapters.media.keys import KeyRing, create_keyring
from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import SqliteMediaCatalogue
from anuvritti.shared.identity import FamilyId, Uuid7IdGenerator


def test_keyring_dual_read_rotation():
    key1 = Fernet.generate_key().decode()
    key2 = Fernet.generate_key().decode()

    # Initial state: Key 1 is active
    ring = KeyRing(active_key=key1)
    secret_bytes = b"Audio of first words: 'mama'"

    cipher_v1 = ring.encrypt(secret_bytes)
    assert ring.decrypt(cipher_v1) == secret_bytes

    # Rotate active key to Key 2 (Key 1 becomes historical)
    ring.rotate_active_key(key2)
    assert ring.active_key == key2
    assert ring.historical_keys == [key1]

    # Legacy media still decrypts cleanly!
    assert ring.decrypt(cipher_v1) == secret_bytes

    # New write uses Key 2
    cipher_v2 = ring.encrypt(b"Second memory: tricycle")
    assert ring.decrypt(cipher_v2) == b"Second memory: tricycle"

    # Re-wrap cipher_v1 to Key 2
    rewrapped = ring.rotate_payload(cipher_v1)
    # Removing Key 1 from keyring: rewrapped ciphertext still decrypts with Key 2!
    ring_key2_only = KeyRing(active_key=key2)
    assert ring_key2_only.decrypt(rewrapped) == secret_bytes


def test_media_store_with_rotated_keys_and_rewrapping(tmp_path: Path):
    key_old = Fernet.generate_key().decode()
    key_new = Fernet.generate_key().decode()

    # Use real SQLite database with official migration
    conn = connect(str(tmp_path / "keyrot.db"))
    migrate(conn)
    catalogue = SqliteMediaCatalogue(conn)
    ids = Uuid7IdGenerator()

    # 1. Create media store with old key and write a photo
    ring = create_keyring(f"{key_old}")
    store = EncryptedFilesystemMediaStore(
        root=tmp_path / "media",
        catalogue=catalogue,
        ids=ids,
        encryption_key=ring,
        max_bytes=10_000_000,
        allowed_mime_types=frozenset(["image/jpeg"]),
    )

    family_id = FamilyId("fam-rot-1")
    photo_data = b"\xff\xd8\xff\xe0" + b"old photo bytes"
    put_res = store.put(
        family_id,
        content=photo_data,
        mime_type="image/jpeg",
        at=datetime.now(UTC),
    )
    assert put_res.is_ok()
    media_id = put_res.unwrap().id

    # 2. Rotate store keyring to use new key while keeping old key historical
    ring.rotate_active_key(key_new)

    # Old media is read successfully with zero downtime
    get_res = store.get(media_id)
    assert get_res.is_ok()
    assert get_res.unwrap() == photo_data

    # New media write succeeds with the new key
    new_photo = b"\xff\xd8\xff\xe0" + b"new photo bytes"
    put_new_res = store.put(
        family_id,
        content=new_photo,
        mime_type="image/jpeg",
        at=datetime.now(UTC),
    )
    assert put_new_res.is_ok()
    assert store.get(put_new_res.unwrap().id).unwrap() == new_photo

    # 3. Perform gradual re-wrapping across media store
    report = store.rewrap_all()
    assert report.rewrapped >= 1
    # The only question step 4 is allowed to ask. Retiring key_old below is safe because
    # nothing was left behind, and the report says so rather than the count implying it.
    assert report.retirable, report.failed
    assert report.inspected >= report.rewrapped

    # 4. Now decommission key_old completely from a new store instance (key_new only)
    store_new_only = EncryptedFilesystemMediaStore(
        root=tmp_path / "media",
        catalogue=catalogue,
        ids=ids,
        encryption_key=key_new,
        max_bytes=10_000_000,
        allowed_mime_types=frozenset(["image/jpeg"]),
    )
    # Old media must decrypt using only key_new because it was re-wrapped!
    assert store_new_only.get(media_id).unwrap() == photo_data


def test_cli_rotate_media_directory(tmp_path: Path):
    key_old = Fernet.generate_key().decode()
    key_new = Fernet.generate_key().decode()

    conn = connect(str(tmp_path / "cli_keyrot.db"))
    migrate(conn)
    catalogue = SqliteMediaCatalogue(conn)
    ids = Uuid7IdGenerator()

    store = EncryptedFilesystemMediaStore(
        root=tmp_path / "cli_media",
        catalogue=catalogue,
        ids=ids,
        encryption_key=key_old,
        max_bytes=10_000_000,
        allowed_mime_types=frozenset(["image/jpeg"]),
    )

    family_id = FamilyId("fam-cli-1")
    photo = b"\xff\xd8\xff\xe0" + b"cli test photo bytes"
    put_res = store.put(family_id, content=photo, mime_type="image/jpeg", at=datetime.now(UTC))
    media_id = put_res.unwrap().id

    # Run CLI function with new key first, then old key
    report = rotate_media_directory(tmp_path / "cli_media", f"{key_new},{key_old}")
    assert report.rewrapped >= 1
    assert report.retirable, report.failed

    # Verify key_old can be retired
    store_retired = EncryptedFilesystemMediaStore(
        root=tmp_path / "cli_media",
        catalogue=catalogue,
        ids=ids,
        encryption_key=key_new,
        max_bytes=10_000_000,
        allowed_mime_types=frozenset(["image/jpeg"]),
    )
    assert store_retired.get(media_id).unwrap() == photo


def test_a_file_no_key_opens_makes_the_rotation_unretirable(tmp_path: Path):
    """The failure that costs a family its photos, and the report that prevents it.

    A media directory can hold an object written under a key that is no longer in the
    ring - a restore from an older backup, a key an operator dropped from the CSV by
    hand. Re-wrapping cannot touch it. If the walk says "12 files re-wrapped" and stops
    there, the operator retires the historical keys and that object is gone forever, so
    the walk names it and `retirable` goes false.
    """
    key_new = Fernet.generate_key().decode()
    stranger = Fernet.generate_key().decode()

    media = tmp_path / "orphan_media"
    media.mkdir()
    (media / "readable.bin").write_bytes(Fernet(key_new.encode()).encrypt(b"a photo"))
    (media / "lost.bin").write_bytes(Fernet(stranger.encode()).encrypt(b"a voice note"))

    report = rewrap_directory(media, create_keyring(key_new))

    assert report.inspected == 2
    assert not report.retirable
    assert report.failed == ("lost.bin",)
    # And the readable one was still processed - one unreadable file does not abort
    # the rotation for everything after it in the walk.
    assert Fernet(key_new.encode()).decrypt((media / "readable.bin").read_bytes()) == b"a photo"
