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
from anuvritti.domain.return_engine import Suggestion, describe_elapsed
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import IntentType, SourceKind, Visibility
from anuvritti.domain.voice import VoiceNote

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
    """`family_id` and `owner_id` are optional because the token already says who this is.

    They remain *accepted* so a client that believes it knows can be told when it is wrong
    (TASK-511): a mismatch is a 403, not a silently redirected write into the right family.
    """

    family_id: str | None = None
    owner_id: str | None = None
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

    created_by: str | None = None
    happened_on: date | None = None
    reflection: str | None = Field(default=None, max_length=4000)
    photo_media_id: str | None = None
    audio_media_id: str | None = None


class SuggestionResponseRequest(Strict):
    response: Literal["maybe_later", "lets_do_it", "not_relevant_anymore"]


class CaptureLittleThingRequest(Strict):
    family_id: str | None = None
    author_id: str | None = None
    subject_child_id: str | None = None
    text: str | None = Field(default=None, max_length=4000)
    audio_media_id: str | None = None


class CaptureRightNowRequest(Strict):
    family_id: str | None = None
    child_id: str
    answer: str = Field(min_length=1, max_length=4000)
    prompt: str | None = Field(default=None, max_length=400)


# ---------------------------------------------------------------------- voice
class KeepVoiceNoteRequest(Strict):
    """The recording is already uploaded; this says how long it is and what it may say.

    `duration_seconds` has no `ge` bound below zero-ish and deliberately no minimum at all.
    PRD 24: nothing is rejected for being unpolished, and a Pydantic `gt=0.5` here would be
    the whole constitution quietly undone by a validator. The domain rejects a *negative*
    duration, which is a broken client rather than a short recording.

    `heard_text` is what the handset's own recogniser made of it. It is stored with machine
    provenance whatever the phone believes about itself (PRD 8.7).
    """

    family_id: str | None = None
    author_id: str | None = None
    media_id: str
    duration_seconds: float
    heard_text: str | None = Field(default=None, max_length=20_000)
    heard_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class CorrectTranscriptRequest(Strict):
    """What was actually said. Permanent, and it never touches the audio."""

    text: str = Field(min_length=1, max_length=20_000)


# ------------------------------------------------------------------- pairing
class ClaimPairingRequest(Strict):
    """Eight characters read off a phone already inside the house, and a name for this one.

    `code` deliberately carries no `min_length`. It is the one field in this file where
    Pydantic validating the shape would be a security bug: a 422 for an empty code and a 401
    for a wrong one are two different answers, and the difference tells a caller that their
    guess was at least the right shape. Every code that is not the code must be refused
    identically, so the string goes to `PairingCode.parse` whatever it looks like.

    `max_length` stays. It is not about which codes exist - it is a bound on how much work
    an unauthenticated caller can ask for in one request.
    """

    code: str = Field(max_length=200)
    device_name: str = Field(min_length=1, max_length=60)


# ------------------------------------------------------------------ renderers
def render_spark(spark: Spark, *, now: datetime, voice: VoiceNote | None = None) -> dict[str, Any]:
    """Provenance is always on the wire (PRD 13, 42). It is not an optional expansion.

    `saved` is the other half of TASK-507. The server does the arithmetic and hands over the
    *phrase*, because a client that receives a day count will eventually render one - not out
    of malice, but because "247" is right there and the deadline is Friday. `created_at` stays
    for ordering and for the export; the interface never needs to subtract it from anything.

    `voice` is the recording behind the why, when the caller has it to hand. It rides inside
    `why` rather than beside it because that is the relationship: the recording *is* the
    answer, and the text is a second, lesser way of giving the same answer (TASK-602).
    """
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
        "why": _render_why(spark, voice=voice),
        "status": spark.status.value,
        "visibility": spark.visibility.value,
        "saved": describe_elapsed(spark.days_since_capture(now)),
        "created_at": spark.created_at.isoformat(),
    }


def render_voice(note: VoiceNote) -> dict[str, Any]:
    """A recording, and whatever is known about what is in it.

    `duration_seconds` is a real number on the wire, and it is the one number in this file
    that is not a scorecard: it is a property of the artifact, the way a photograph has
    dimensions. TASK-707 will measure a film against it, so it has to be measured rather
    than described - `describe_elapsed` exists for time that has *passed*, not for length.

    `transcript` is nested rather than flattened so that a client physically cannot render
    the words without the provenance sitting in the same object (PRD 8.7).
    """
    return {
        "media_id": str(note.media_id),
        "duration_seconds": note.duration_seconds,
        "recorded_at": note.recorded_at.isoformat(),
        "transcript": note.transcript.to_dict() if note.transcript else None,
    }


def render_suggestion(
    suggestion: Suggestion, *, now: datetime, voice: VoiceNote | None = None
) -> dict[str, Any]:
    """PRD 8.5 - no counters, no urgency, no score on the wire.

    The score is a ranking device, not something to show a parent about their own child.

    `days_since_capture` used to be here, and its removal is TASK-507. It was the one field
    on the whole wire that handed an interface a number about a family's own life, and every
    interesting misuse of this product starts with rendering it: "247 days", then "8 months
    overdue", then a badge. `elapsed` is the same fact with the precision deliberately gone.
    """
    return {
        "spark": render_spark(suggestion.spark, now=now, voice=voice),
        "reason": suggestion.reason,
        "elapsed": describe_elapsed(suggestion.days_since_capture),
        "actions": list(suggestion.actions),
    }


def render_device(device: Any) -> dict[str, Any]:
    """A paired device, as a parent deciding what to revoke would need to see it.

    No token, no fingerprint, no request count. `last_seen_at` is the only usage fact kept,
    and it exists so "revoke the one I lost" has an answer.
    """
    return {
        "id": str(device.id),
        "display_name": device.display_name,
        "created_at": device.created_at.isoformat(),
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "revoked": device.is_revoked,
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


def _render_why(spark: Spark, *, voice: VoiceNote | None) -> dict[str, Any] | None:
    if spark.why is None:
        return None
    return {**spark.why.to_dict(), "voice": render_voice(voice) if voice else None}


def render_little_thing(thing: LittleThing, *, voice: VoiceNote | None = None) -> dict[str, Any]:
    """PRD 17. `voice` first in the object, and `text` after it.

    Key order in JSON is not semantics and every client is free to ignore it. It is still
    written this way, because the shape of a payload is the first thing anyone reads when
    they build a screen against it, and this one should read as: there is a recording, and
    there are some words about it.
    """
    return {
        "id": str(thing.id),
        "voice": render_voice(voice) if voice else None,
        "audio_media_id": thing.audio_media_id,
        "text": thing.text,
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
    "ClaimPairingRequest",
    "CorrectTranscriptRequest",
    "CreateChildRequest",
    "CreateFamilyRequest",
    "KeepVoiceNoteRequest",
    "MarkAsDoneRequest",
    "OverrideFieldRequest",
    "RecordWhyRequest",
    "SourceRequest",
    "SuggestionResponseRequest",
    "V0Intent",
    "datetime",
    "parse_intent",
    "render_device",
    "render_family",
    "render_little_thing",
    "render_moment",
    "render_right_now",
    "render_spark",
    "render_suggestion",
    "render_voice",
]
