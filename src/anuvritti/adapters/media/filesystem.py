"""Encrypted, content-addressed media store (PRD 44, HARDENING 5.5).

The bytes here are a child's face and a family's voice. Three properties follow:

* **Encrypted at rest with key rotation.** Keys are managed via a KeyRing with zero-downtime
  historical key support.
* **Content-addressed.** The same photo saved twice occupies one file, and a corrupted
  read is detectable rather than silently wrong.
* **Actually deletable.** `delete_for_family` unlinks bytes, because PRD 44 promises
  "delete everything" and a promise you cannot execute is not a promise.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from cryptography.fernet import InvalidToken

from anuvritti.adapters.media.keys import KeyRing, create_keyring
from anuvritti.domain.media import MediaKind, MediaObject
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId, IdGenerator, MediaId
from anuvritti.shared.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class Rewrap:
    """The outcome of a key rotation, as an operator has to read it.

    HARDENING 5.5 promises zero-downtime rotation, and the dangerous half of that promise
    is the step *after*: retiring the old key. That is safe only when every stored object
    now opens with the new one, so the report says which files did not, and `retirable`
    is the single question `scripts/rotate_keys.py` asks before telling anyone it is done.
    """

    inspected: int
    rewrapped: int
    failed: tuple[str, ...]

    @property
    def retirable(self) -> bool:
        """True when no file was left behind, so historical keys can be dropped."""
        return not self.failed


class _Catalogue(Protocol):
    """The metadata half of the store. Implemented by SqliteMediaCatalogue."""

    def record(self, media: MediaObject) -> None: ...

    def find(self, media_id: MediaId) -> MediaObject | None: ...

    def list_for_family(self, family_id: FamilyId) -> list[MediaObject]: ...

    def delete_for_family(self, family_id: FamilyId) -> int: ...


class EncryptedFilesystemMediaStore:
    """Files on disk, encrypted with Fernet/KeyRing, indexed by a SQLite catalogue."""

    def __init__(
        self,
        *,
        root: Path,
        catalogue: _Catalogue,
        ids: IdGenerator,
        encryption_key: str | KeyRing | None,
        max_bytes: int,
        allowed_mime_types: frozenset[str],
    ) -> None:
        self._root = root
        self._catalogue = catalogue
        self._ids = ids
        self._keyring: KeyRing | None = create_keyring(encryption_key) if encryption_key else None
        self._max_bytes = max_bytes
        self._allowed = allowed_mime_types
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def encrypts_at_rest(self) -> bool:
        return self._keyring is not None

    @property
    def keyring(self) -> KeyRing | None:
        return self._keyring

    # -------------------------------------------------------------------- put
    def put(
        self, family_id: FamilyId, *, content: bytes, mime_type: str, at: datetime
    ) -> Result[MediaObject, DomainError]:
        if not content:
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "media content is empty"))
        if len(content) > self._max_bytes:
            return Err(
                DomainError(
                    ErrorCode.MEDIA_TOO_LARGE,
                    f"media exceeds {self._max_bytes} bytes",
                    {"byte_size": len(content), "limit": self._max_bytes},
                )
            )
        normalised = mime_type.split(";")[0].strip().lower()
        if normalised not in self._allowed:
            return Err(
                DomainError(
                    ErrorCode.MEDIA_KIND_UNSUPPORTED,
                    f"{normalised} is not an accepted media type",
                    {"allowed": sorted(self._allowed)},
                )
            )
        kind = MediaKind.for_mime_type(normalised)
        if kind is None:  # pragma: no cover - the allow-list already excludes these
            return Err(DomainError(ErrorCode.MEDIA_KIND_UNSUPPORTED, normalised))

        content_hash = hashlib.sha256(content).hexdigest()
        media_id = MediaId(self._ids.new_id())
        storage_key = f"{family_id}/{content_hash[:2]}/{content_hash}"

        target = self._root / storage_key
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            # Content-addressed: identical bytes are stored once, per family.
            target.write_bytes(self._encrypt(content))

        media = MediaObject(
            id=media_id,
            family_id=family_id,
            kind=kind,
            mime_type=normalised,
            byte_size=len(content),
            content_hash=content_hash,
            storage_key=storage_key,
            encrypted=self.encrypts_at_rest,
            created_at=at,
        )
        self._catalogue.record(media)
        return Ok(media)

    # -------------------------------------------------------------------- get
    def get(self, media_id: MediaId) -> Result[bytes, DomainError]:
        described = self.describe(media_id)
        if described.is_err():
            return Err(described.unwrap_err())
        media = described.unwrap()

        path = self._root / media.storage_key
        if not path.exists():
            return Err(
                DomainError(ErrorCode.MEDIA_NOT_FOUND, f"bytes for {media_id} are gone from disk")
            )

        try:
            content = self._decrypt(path.read_bytes(), encrypted=media.encrypted)
        except InvalidToken:
            return Err(
                DomainError(
                    ErrorCode.MEDIA_NOT_FOUND,
                    f"media {media_id} could not be decrypted with the configured key",
                    {"media_id": str(media_id)},
                )
            )

        if hashlib.sha256(content).hexdigest() != media.content_hash:
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    f"media {media_id} failed its integrity check",
                    {"media_id": str(media_id)},
                )
            )
        return Ok(content)

    def describe(self, media_id: MediaId) -> Result[MediaObject, DomainError]:
        found = self._catalogue.find(media_id)
        if found is None:
            return Err(DomainError(ErrorCode.MEDIA_NOT_FOUND, f"no media {media_id}"))
        return Ok(found)

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[MediaObject], DomainError]:
        return Ok(self._catalogue.list_for_family(family_id))

    # ----------------------------------------------------------------- delete
    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        """PRD 44 - "delete everything" means the bytes, not just the row."""
        known = self._catalogue.list_for_family(family_id)
        for media in known:
            path = self._root / media.storage_key
            path.unlink(missing_ok=True)

        family_dir = self._root / str(family_id)
        if family_dir.exists():
            for path in sorted(family_dir.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink(missing_ok=True)
                else:
                    path.rmdir()
            family_dir.rmdir()

        return Ok(self._catalogue.delete_for_family(family_id))

    # ----------------------------------------------------------------- re-wrapping
    def rewrap_all(self) -> Rewrap:
        """Re-encrypt all stored media on disk under the active primary key.

        Uses `KeyRing.rotate_payload()` so historical keys can eventually be retired -
        and `Rewrap.retirable` is the answer to whether they can be. A count alone
        cannot say that, which is why this does not return one.
        """
        if self._keyring is None:
            return Rewrap(inspected=0, rewrapped=0, failed=())
        return rewrap_directory(self._root, self._keyring)

    # -------------------------------------------------------------- internals
    def _encrypt(self, content: bytes) -> bytes:
        return self._keyring.encrypt(content) if self._keyring else content

    def _decrypt(self, stored: bytes, *, encrypted: bool) -> bytes:
        if not encrypted:
            return stored
        if self._keyring is None:
            raise InvalidToken
        return self._keyring.decrypt(stored)


def rewrap_directory(root: Path, keyring: KeyRing) -> Rewrap:
    """Re-encrypt every file under `root` with `keyring`'s active key.

    Module-level because `scripts/rotate_keys.py` runs it against a media directory that
    has no catalogue, no id generator and no upload limits to enforce - and a second
    implementation of this walk living in the script is how the script and the
    application would come to disagree about what a completed rotation means.
    """
    inspected = rewrapped = 0
    failed: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        inspected += 1
        raw = path.read_bytes()
        try:
            rotated = keyring.rotate_payload(raw)
        except InvalidToken:
            # No key in the ring opens this file. Skipping it silently is how a family
            # loses media: the operator sees a count, believes the rotation was total,
            # retires the old key, and the bytes become unreadable forever. It is named
            # instead, and `retirable` goes false.
            failed.append(path.relative_to(root).as_posix())
            continue
        if rotated != raw:
            path.write_bytes(rotated)
            rewrapped += 1
    return Rewrap(inspected=inspected, rewrapped=rewrapped, failed=tuple(failed))
