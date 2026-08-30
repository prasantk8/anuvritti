"""Media metadata.

The bytes live in a `MediaStore` adapter; this is only what the domain needs to know
about them. PRD 44 requires encryption at rest, so `encrypted` is part of the record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from anuvritti.shared.identity import FamilyId, MediaId


class MediaKind(StrEnum):
    IMAGE = "IMAGE"
    AUDIO = "AUDIO"

    @classmethod
    def for_mime_type(cls, mime_type: str) -> MediaKind | None:
        normalised = mime_type.split(";")[0].strip().lower()
        if normalised.startswith("image/"):
            return cls.IMAGE
        if normalised.startswith("audio/"):
            return cls.AUDIO
        return None


@dataclass(frozen=True, slots=True)
class MediaObject:
    """A stored file, described without ever holding its bytes."""

    id: MediaId
    family_id: FamilyId
    kind: MediaKind
    mime_type: str
    byte_size: int
    content_hash: str
    storage_key: str
    encrypted: bool
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "kind": self.kind.value,
            "mime_type": self.mime_type,
            "byte_size": self.byte_size,
            "encrypted": self.encrypted,
        }
