"""Domain value objects.

Immutable, self-validating, and free of infrastructure. Everything the PRD promises about
intents, provenance and link-rot is enforced here rather than by convention.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, ClassVar, Final, Self
from urllib.parse import urlparse

MAX_CHILD_AGE: Final[int] = 18
_TITLE_MAX: Final[int] = 80


class IntentType(StrEnum):
    """What the person hoped would happen (PRD 10, 13).

    V0 ships six (PRD 48 F4). The rest are modelled now so enabling them in V1 is a
    feature flag rather than a data migration.
    """

    DO = "DO"
    BUY = "BUY"
    WATCH = "WATCH"
    READ = "READ"
    TEACH = "TEACH"
    REMEMBER = "REMEMBER"
    # --- modelled, not shipped in V0 ---
    COOK = "COOK"
    VISIT = "VISIT"
    TELL = "TELL"
    LISTEN = "LISTEN"

    @classmethod
    def v0_set(cls) -> frozenset[IntentType]:
        return frozenset({cls.DO, cls.BUY, cls.WATCH, cls.READ, cls.TEACH, cls.REMEMBER})

    @property
    def is_available_in_v0(self) -> bool:
        return self in IntentType.v0_set()

    @property
    def is_immediately_actionable(self) -> bool:
        """DO and TEACH can happen this weekend; BUY and REMEMBER can wait (PRD 13)."""
        return self in {IntentType.DO, IntentType.TEACH, IntentType.COOK, IntentType.VISIT}


class SparkStatus(StrEnum):
    """The Spark lifecycle (PRD 10)."""

    CAPTURED = "CAPTURED"
    WAITING = "WAITING"
    RELEVANT = "RELEVANT"
    SUGGESTED = "SUGGESTED"
    PLANNED = "PLANNED"
    EXPERIENCED = "EXPERIENCED"
    REMEMBERED = "REMEMBERED"
    ARCHIVED = "ARCHIVED"

    @property
    def is_terminal(self) -> bool:
        return self in {SparkStatus.ARCHIVED, SparkStatus.REMEMBERED}

    @property
    def is_returnable(self) -> bool:
        """Only things still waiting to be lived may be brought back (PRD 14)."""
        return self in {SparkStatus.WAITING, SparkStatus.RELEVANT, SparkStatus.SUGGESTED}

    @property
    def is_lived(self) -> bool:
        return self in {SparkStatus.EXPERIENCED, SparkStatus.REMEMBERED}


class SourceKind(StrEnum):
    URL = "URL"
    TEXT = "TEXT"
    SCREENSHOT = "SCREENSHOT"
    PHOTO = "PHOTO"
    VOICE = "VOICE"

    @property
    def is_media(self) -> bool:
        return self in {SourceKind.SCREENSHOT, SourceKind.PHOTO, SourceKind.VOICE}


class MemberRole(StrEnum):
    PARENT = "PARENT"
    CO_PARENT = "CO_PARENT"
    CHILD = "CHILD"
    GRANDPARENT = "GRANDPARENT"

    @property
    def can_capture_for_child(self) -> bool:
        return self in {MemberRole.PARENT, MemberRole.CO_PARENT}


class Visibility(StrEnum):
    """Who may see this (PRD 44, 45).

    Ordered from most to least private. `PRIVATE` is the default because privacy must be
    the state you fall into, not the state you opt into.
    """

    PRIVATE = "PRIVATE"
    FAMILY = "FAMILY"
    CHILD_VISIBLE = "CHILD_VISIBLE"

    @classmethod
    def default(cls) -> Visibility:
        return cls.PRIVATE

    @property
    def _rank(self) -> int:
        return {Visibility.PRIVATE: 0, Visibility.FAMILY: 1, Visibility.CHILD_VISIBLE: 2}[self]

    def is_more_private_than(self, other: Visibility) -> bool:
        return self._rank < other._rank

    def is_visible_to(self, role: MemberRole) -> bool:
        if self is Visibility.CHILD_VISIBLE:
            return True
        if self is Visibility.FAMILY:
            return role is not MemberRole.CHILD
        return role in {MemberRole.PARENT, MemberRole.CO_PARENT}


class AttributionSource(StrEnum):
    """Where a field's value came from (PRD 8.7 - recorded / human / AI are not the same)."""

    HUMAN = "HUMAN"
    AI = "AI"
    DEFAULT = "DEFAULT"


@dataclass(frozen=True, slots=True, order=True)
class Confidence:
    """How sure the system is. Never presented as truth (PRD 8.7)."""

    value: float

    LOW: ClassVar[Confidence]
    MEDIUM: ClassVar[Confidence]
    HIGH: ClassVar[Confidence]
    CERTAIN: ClassVar[Confidence]

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"confidence must be between 0 and 1, got {self.value}")

    @property
    def is_low(self) -> bool:
        """Low confidence means show it as a question, never as a fact."""
        return self.value < 0.5


Confidence.LOW = Confidence(0.3)
Confidence.MEDIUM = Confidence(0.6)
Confidence.HIGH = Confidence(0.85)
Confidence.CERTAIN = Confidence(1.0)


@dataclass(frozen=True, slots=True)
class AgeRange:
    """The window in which something is likely to land well (PRD 13)."""

    min_years: int
    max_years: int

    def __post_init__(self) -> None:
        if self.min_years < 0 or self.max_years < 0:
            raise ValueError("age cannot be negative")
        if self.min_years > self.max_years:
            raise ValueError(f"min_years {self.min_years} exceeds max_years {self.max_years}")
        if self.max_years > MAX_CHILD_AGE:
            raise ValueError(f"age range may not exceed {MAX_CHILD_AGE} years")

    def contains(self, age_years: int) -> bool:
        return self.min_years <= age_years <= self.max_years

    def years_until(self, age_years: int) -> int:
        """Years until the child grows into this. Zero if they are in it, or past it."""
        return max(0, self.min_years - age_years)

    def to_dict(self) -> dict[str, int]:
        return {"min_years": self.min_years, "max_years": self.max_years}


@dataclass(frozen=True, slots=True)
class Attributed[T]:
    """A field plus the story of where it came from (PRD 13, 42; ADR-0005).

    Persisted as four discrete columns so a serializer can never quietly drop the
    provenance and leave an AI guess looking like a fact.
    """

    value: T
    source: AttributionSource
    confidence: Confidence
    human_override: bool

    @classmethod
    def inferred(cls, value: T, confidence: Confidence) -> Self:
        return cls(value, AttributionSource.AI, confidence, human_override=False)

    @classmethod
    def stated(cls, value: T) -> Self:
        """A human said so. That is the end of the discussion."""
        return cls(value, AttributionSource.HUMAN, Confidence.CERTAIN, human_override=True)

    @classmethod
    def defaulted(cls, value: T) -> Self:
        return cls(value, AttributionSource.DEFAULT, Confidence(0.0), human_override=False)

    @property
    def may_reinfer(self) -> bool:
        return not self.human_override

    def override(self, value: T) -> Self:
        """Replace the value with a human statement and lock the field."""
        return type(self).stated(value)

    def reinferred(self, value: T, confidence: Confidence) -> Self:
        """Apply a fresh inference - unless a human has already spoken."""
        if not self.may_reinfer:
            return self
        return type(self).inferred(value, confidence)

    def to_dict(self) -> dict[str, Any]:
        value: Any = self.value
        if isinstance(value, AgeRange):
            value = value.to_dict()
        elif isinstance(value, StrEnum):
            value = value.value
        return {
            "value": value,
            "source": self.source.value,
            "confidence": self.confidence.value,
            "human_override": self.human_override,
        }


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Where the Spark came from.

    PRD 43: Anuvritti does not assume it can keep third-party media forever. It keeps the
    context that makes the Spark meaningful even after the link rots.
    """

    kind: SourceKind
    url: str | None = None
    creator: str | None = None
    title: str | None = None
    text: str | None = None
    media_id: str | None = None

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        creator: str | None = None,
        title: str | None = None,
        text: str | None = None,
    ) -> Self:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"source url must be http or https, got {parsed.scheme!r}")
        if not parsed.netloc:
            raise ValueError("source url must have a host")
        return cls(SourceKind.URL, url=url, creator=creator, title=title, text=text)

    @classmethod
    def from_text(cls, text: str) -> Self:
        if not text.strip():
            raise ValueError("a text source requires text")
        return cls(SourceKind.TEXT, text=text.strip())

    @classmethod
    def from_media(cls, kind: SourceKind, *, media_id: str, text: str | None = None) -> Self:
        if not kind.is_media:
            raise ValueError(f"kind {kind} is not a media kind")
        if not media_id.strip():
            raise ValueError("a media source requires a media_id")
        return cls(kind, media_id=media_id, text=text)

    @property
    def retains_meaning_without_network(self) -> bool:
        """PRD 43 - would this Spark still say something if the link disappeared today?"""
        if self.kind is SourceKind.URL:
            return bool(self.title or self.creator or self.text)
        return bool(self.text or self.media_id)

    def display_title(self) -> str:
        if self.title:
            return self.title[:_TITLE_MAX]
        if self.text:
            return self.text.strip()[:_TITLE_MAX].strip()
        if self.url:
            return urlparse(self.url).netloc
        return self.kind.value.title()

    def with_preserved_context(self, *, creator: str | None, title: str | None) -> Self:
        return replace(self, creator=creator or self.creator, title=title or self.title)
