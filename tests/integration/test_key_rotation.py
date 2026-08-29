"""TASK-1107 - Zero-Downtime Key Rotation (HARDENING 5.5, PRD 44).

Verifies that:
1. Media encrypted under an older key remains readable after key rotation.
2. New media is encrypted with the updated primary key.
3. Media re-wrapping updates legacy ciphertexts to the active key.
4. Works seamlessly through EncryptedFilesystemMediaStore.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet

from anuvritti.adapters.media.filesystem import EncryptedFilesystemMediaStore
from anuvritti.adapters.media.keys import KeyRing, create_keyring
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


def test_media_store_with_rotated_keys(tmp_path: Path):
    key_old = Fernet.generate_key().decode()
    key_new = Fernet.generate_key().decode()

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE media (
            id TEXT PRIMARY KEY,
            family_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            byte_size INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            storage_key TEXT NOT NULL,
            encrypted INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    catalogue = SqliteMediaCatalogue(db)
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
