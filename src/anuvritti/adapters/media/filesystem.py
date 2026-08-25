"""Encrypted, content-addressed media store (PRD 44).

The bytes here are a child's face and a family's voice. Three properties follow:

* **Encrypted at rest.** The key comes from the environment and never from the repo. In
  development a store may run unencrypted; production refuses to start without a key.
* **Content-addressed.** The same photo saved twice occupies one file, and a corrupted
  read is detectable rather than silently wrong.
* **Actually deletable.** `delete_for_family` unlinks bytes, because PRD 44 promises
  "delete everything" and a promise you cannot execute is not a promise.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken

from anuvritti.domain.media import MediaKind, MediaObject
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId, IdGenerator, MediaId
from anuvritti.shared.result import Err, Ok, Result


class _Catalogue(Protocol):
    """The metadata half of the store. Implemented by SqliteMediaCatalogue."""

    def record(self, media: MediaObject) -> None: ...

    def find(self, media_id: MediaId) -> MediaObject | None: ...

    def list_for_family(self, family_id: FamilyId) -> list[MediaObject]: ...

    def delete_for_family(self, family_id: FamilyId) -> int: ...


class EncryptedFilesystemMediaStore:
    """Files on disk, encrypted with Fernet, indexed by a SQLite catalogue."""

    def __init__(
        self,
        *,
        root: Path,
        catalogue: _Catalogue,
        ids: IdGenerator,
        encryption_key: str | None,
        max_bytes: int,
        allowed_mime_types: frozenset[str],
    ) -> None:
        self._root = root
        self._catalogue = catalogue
        self._ids = ids
        self._fernet = Fernet(encryption_key.encode()) if encryption_key else None
        self._max_bytes = max_bytes
        self._allowed = allowed_mime_types
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def encrypts_at_rest(self) -> bool:
        return self._fernet is not None

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

    # -------------------------------------------------------------- internals
    def _encrypt(self, content: bytes) -> bytes:
        return self._fernet.encrypt(content) if self._fernet else content

    def _decrypt(self, stored: bytes, *, encrypted: bool) -> bytes:
        if not encrypted:
            return stored
        if self._fernet is None:
            raise InvalidToken
        return self._fernet.decrypt(stored)
