"""The published error catalog.

Codes are a contract (docs/contracts/errors.md). Clients switch on `code`, never on prose.
A test asserts that the documented codes and this enum never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class ErrorCode(StrEnum):
    VALIDATION_FAILED = "VALIDATION_FAILED"
    FAMILY_NOT_FOUND = "FAMILY_NOT_FOUND"
    MEMBER_NOT_FOUND = "MEMBER_NOT_FOUND"
    CHILD_NOT_FOUND = "CHILD_NOT_FOUND"
    SPARK_NOT_FOUND = "SPARK_NOT_FOUND"
    MOMENT_NOT_FOUND = "MOMENT_NOT_FOUND"
    MEDIA_NOT_FOUND = "MEDIA_NOT_FOUND"
    SPARK_INVALID_TRANSITION = "SPARK_INVALID_TRANSITION"
    SPARK_ARCHIVED = "SPARK_ARCHIVED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    PAIRING_FAILED = "PAIRING_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CAPTURE_SOURCE_INVALID = "CAPTURE_SOURCE_INVALID"
    MEDIA_TOO_LARGE = "MEDIA_TOO_LARGE"
    MEDIA_KIND_UNSUPPORTED = "MEDIA_KIND_UNSUPPORTED"
    CONFLICT = "CONFLICT"


_EMPTY: MappingProxyType[str, Any] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class DomainError:
    """An expected failure. Never raised across a boundary - always returned in an `Err`."""

    code: ErrorCode
    message: str
    details: Any = field(default=_EMPTY)

    def __post_init__(self) -> None:
        if self.details is _EMPTY:
            object.__setattr__(self, "details", {})

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DomainError):
            return NotImplemented
        return (self.code, self.message, dict(self.details)) == (
            other.code,
            other.message,
            dict(other.details),
        )

    def __hash__(self) -> int:
        return hash((self.code, self.message, tuple(sorted(dict(self.details).items()))))

    def to_dict(self) -> dict[str, Any]:
        """The wire envelope fixed by docs/contracts/errors.md."""
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "details": dict(self.details),
            }
        }
