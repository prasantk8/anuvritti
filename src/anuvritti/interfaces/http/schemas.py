"""Wire schemas.

Pydantic lives here and nowhere else. The domain must never learn what a request body
looks like, and the API must never leak a domain type it did not intend to publish.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from anuvritti.domain.moment import Moment
from anuvritti.domain.presence import LittleThing, RightNowSnapshot
from anuvritti.domain.return_engine import Suggestion
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import IntentType, SourceKind, Visibility

V0Intent = Literal["DO", "BUY", "WATCH", "READ", "TEACH", "REMEMBER"]


class Strict(BaseModel):
    """Reject unknown fields.

    A typo in a client should be a 422, not a silently ignored preference about a child.
    """

    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------- families
class CreateFamilyRequest(Strict):
    name: str = Field(min_length=1, max_length=120)
    owner_display_name: str = Field(min_length=1, max_length=120)


class CreateChildRequest(Strict):
    display_name: str = Field(min_length=1, max_length=120)
    date_of_birth: date


# --------------------------------------------------------------------- sparks
class SourceRequest(Strict):
    kind: SourceKind
    url: str | None = None
    text: str | None = None
    creator: str | None = None
    title: str | None = None
    media_id: str | None = None


class CaptureSparkRequest(Strict):
    family_id: str
    owner_id: str
    source: SourceRequest
    subject_child_id: str | None = None
    note: str | None = Field(default=None, max_length=2000)
    visibility: Visibility | None = None


class RecordWhyRequest(Strict):
    text: str | None = Field(default=None, max_length=2000)
    voice_media_id: str | None = None


class OverrideFieldRequest(Strict):
    field: Literal["intent", "age_range", "category"]
    value: Any


class MarkAsDoneRequest(Strict):
    """Every field optional - "nothing" is a valid answer (PRD 15)."""

    created_by: str
    happened_on: date | None = None
    reflection: str | None = Field(default=None, max_length=4000)
    photo_media_id: str | None = None
    audio_media_id: str | None = None


class SuggestionResponseRequest(Strict):
    response: Literal["maybe_later", "lets_do_it", "not_relevant_anymore"]


class CaptureLittleThingRequest(Strict):
    family_id: str
    author_id: str
    subject_child_id: str | None = None
    text: str | None = Field(default=None, max_length=4000)
    audio_media_id: str | None = None


class CaptureRightNowRequest(Strict):
    family_id: str
    child_id: str
    answer: str = Field(min_length=1, max_length=4000)
    prompt: str | None = Field(default=None, max_length=400)


# ------------------------------------------------------------------ renderers
def render_spark(spark: Spark) -> dict[str, Any]:
    """Provenance is always on the wire (PRD 13, 42). It is not an optional expansion."""
    return {
        "id": str(spark.id),
        "family_id": str(spark.family_id),
        "owner_id": str(spark.owner_id),
        "subject_child_id": str(spark.subject_child_id) if spark.subject_child_id else None,
        "title": spark.title,
        "note": spark.note,
        "source": {
            "kind": spark.source.kind.value,
            "url": spark.source.url,
            "creator": spark.source.creator,
            "title": spark.source.title,
            "media_id": spark.source.media_id,
        },
        "intent": spark.intent.to_dict(),
        "category": spark.category.to_dict(),
        "age_range": spark.age_range.to_dict() if spark.age_range else None,
        "tags": list(spark.tags),
        "why": spark.why.to_dict() if spark.why else None,
        "status": spark.status.value,
        "visibility": spark.visibility.value,
        "created_at": spark.created_at.isoformat(),
    }


def render_suggestion(suggestion: Suggestion) -> dict[str, Any]:
    """PRD 8.5 - no counters, no urgency, no score on the wire.

    The score is a ranking device, not something to show a parent about their own child.
    """
    return {
        "spark": render_spark(suggestion.spark),
        "reason": suggestion.reason,
        "days_since_capture": suggestion.days_since_capture,
        "actions": list(suggestion.actions),
    }


def render_moment(moment: Moment) -> dict[str, Any]:
    return {
        "id": str(moment.id),
        "spark_id": str(moment.spark_id),
        "happened_on": moment.happened_on.isoformat(),
        "reflection": moment.reflection,
        "photo_media_id": moment.photo_media_id,
        "audio_media_id": moment.audio_media_id,
        "created_at": moment.created_at.isoformat(),
    }


def render_little_thing(thing: LittleThing) -> dict[str, Any]:
    return {
        "id": str(thing.id),
        "text": thing.text,
        "audio_media_id": thing.audio_media_id,
        "created_at": thing.created_at.isoformat(),
    }


def render_right_now(snapshot: RightNowSnapshot) -> dict[str, Any]:
    return {
        "id": str(snapshot.id),
        "child_id": str(snapshot.child_id),
        "prompt": snapshot.prompt,
        "answer": snapshot.answer,
        "captured_at": snapshot.captured_at.isoformat(),
    }


def render_family(family: Any, today: date) -> dict[str, Any]:
    return {
        "id": str(family.id),
        "name": family.name,
        "members": [
            {"id": str(m.id), "display_name": m.display_name, "role": m.role.value}
            for m in family.members
        ],
        "children": [
            {
                "id": str(c.id),
                "display_name": c.display_name,
                "date_of_birth": c.date_of_birth.isoformat(),
                "age_years": c.age_years(today),
            }
            for c in family.children
        ],
    }


def parse_intent(value: Any) -> IntentType | None:
    try:
        intent = IntentType(str(value).upper())
    except ValueError:
        return None
    return intent if intent.is_available_in_v0 else None


__all__ = [
    "CaptureLittleThingRequest",
    "CaptureRightNowRequest",
    "CaptureSparkRequest",
    "CreateChildRequest",
    "CreateFamilyRequest",
    "MarkAsDoneRequest",
    "OverrideFieldRequest",
    "RecordWhyRequest",
    "SourceRequest",
    "SuggestionResponseRequest",
    "V0Intent",
    "datetime",
    "parse_intent",
    "render_family",
    "render_little_thing",
    "render_moment",
    "render_right_now",
    "render_spark",
    "render_suggestion",
]
