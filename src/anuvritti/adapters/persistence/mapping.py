"""Row <-> domain object mapping.

Kept in one module so there is exactly one place where the shape of the database and the
shape of the domain meet. Every function here is total: a row either maps to a valid
aggregate or the archive is corrupt, and corruption is not an expected failure.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

from anuvritti.domain.family import ChildProfile, Family, Member
from anuvritti.domain.media import MediaKind, MediaObject
from anuvritti.domain.moment import Moment
from anuvritti.domain.presence import LittleThing, RightNowSnapshot
from anuvritti.domain.spark import Spark, Why
from anuvritti.domain.values import (
    AgeRange,
    Attributed,
    AttributionSource,
    Confidence,
    IntentType,
    MemberRole,
    SourceKind,
    SourceRef,
    SparkStatus,
    Visibility,
)
from anuvritti.domain.voice import Transcript, VoiceNote
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    LittleThingId,
    MediaId,
    MemberId,
    MomentId,
    RightNowId,
    SparkId,
)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _require_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def spark_to_row(spark: Spark) -> dict[str, object]:
    age = spark.age_range
    why = spark.why
    return {
        "id": str(spark.id),
        "family_id": str(spark.family_id),
        "owner_id": str(spark.owner_id),
        "subject_child_id": str(spark.subject_child_id) if spark.subject_child_id else None,
        "title": spark.title,
        "note": spark.note,
        "source_kind": spark.source.kind.value,
        "source_url": spark.source.url,
        "source_creator": spark.source.creator,
        "source_title": spark.source.title,
        "source_text": spark.source.text,
        "source_media_id": str(spark.source.media_id) if spark.source.media_id else None,
        "intent_value": spark.intent.value.value,
        "intent_source": spark.intent.source.value,
        "intent_confidence": spark.intent.confidence.value,
        "intent_overridden": int(spark.intent.human_override),
        "category_value": spark.category.value,
        "category_source": spark.category.source.value,
        "category_confidence": spark.category.confidence.value,
        "category_overridden": int(spark.category.human_override),
        "age_min": age.value.min_years if age else None,
        "age_max": age.value.max_years if age else None,
        "age_source": age.source.value if age else None,
        "age_confidence": age.confidence.value if age else None,
        "age_overridden": int(age.human_override) if age else None,
        "tags_json": json.dumps(list(spark.tags)),
        "why_text": why.text if why else None,
        "why_voice_media_id": (str(why.voice_media_id) if why and why.voice_media_id else None),
        "why_recorded_at": why.recorded_at.isoformat() if why else None,
        "status": spark.status.value,
        "visibility": spark.visibility.value,
        "suggested_count": spark.suggested_count,
        "last_suggested_at": (
            spark.last_suggested_at.isoformat() if spark.last_suggested_at else None
        ),
        "snoozed_until": spark.snoozed_until.isoformat() if spark.snoozed_until else None,
        "created_at": spark.created_at.isoformat(),
        "updated_at": spark.updated_at.isoformat(),
    }


def row_to_spark(row: sqlite3.Row) -> Spark:
    age_range: Attributed[AgeRange] | None = None
    if row["age_min"] is not None:
        age_range = Attributed(
            value=AgeRange(row["age_min"], row["age_max"]),
            source=AttributionSource(row["age_source"]),
            confidence=Confidence(row["age_confidence"]),
            human_override=bool(row["age_overridden"]),
        )

    why: Why | None = None
    if row["why_text"] or row["why_voice_media_id"]:
        why = Why(
            text=row["why_text"],
            voice_media_id=row["why_voice_media_id"],
            recorded_at=_require_dt(row["why_recorded_at"]),
        )

    return Spark(
        id=SparkId(row["id"]),
        family_id=FamilyId(row["family_id"]),
        owner_id=MemberId(row["owner_id"]),
        subject_child_id=ChildId(row["subject_child_id"]) if row["subject_child_id"] else None,
        title=row["title"],
        note=row["note"],
        source=SourceRef(
            kind=SourceKind(row["source_kind"]),
            url=row["source_url"],
            creator=row["source_creator"],
            title=row["source_title"],
            text=row["source_text"],
            media_id=row["source_media_id"],
        ),
        intent=Attributed(
            value=IntentType(row["intent_value"]),
            source=AttributionSource(row["intent_source"]),
            confidence=Confidence(row["intent_confidence"]),
            human_override=bool(row["intent_overridden"]),
        ),
        category=Attributed(
            value=row["category_value"],
            source=AttributionSource(row["category_source"]),
            confidence=Confidence(row["category_confidence"]),
            human_override=bool(row["category_overridden"]),
        ),
        age_range=age_range,
        tags=tuple(json.loads(row["tags_json"])),
        why=why,
        status=SparkStatus(row["status"]),
        visibility=Visibility(row["visibility"]),
        suggested_count=row["suggested_count"],
        last_suggested_at=_dt(row["last_suggested_at"]),
        snoozed_until=_dt(row["snoozed_until"]),
        created_at=_require_dt(row["created_at"]),
        updated_at=_require_dt(row["updated_at"]),
    )


def row_to_moment(row: sqlite3.Row) -> Moment:
    return Moment(
        id=MomentId(row["id"]),
        family_id=FamilyId(row["family_id"]),
        spark_id=SparkId(row["spark_id"]),
        happened_on=date.fromisoformat(row["happened_on"]),
        reflection=row["reflection"],
        photo_media_id=row["photo_media_id"],
        audio_media_id=row["audio_media_id"],
        created_by=MemberId(row["created_by"]),
        created_at=_require_dt(row["created_at"]),
    )


def row_to_little_thing(row: sqlite3.Row) -> LittleThing:
    return LittleThing(
        id=LittleThingId(row["id"]),
        family_id=FamilyId(row["family_id"]),
        author_id=MemberId(row["author_id"]),
        subject_child_id=ChildId(row["subject_child_id"]) if row["subject_child_id"] else None,
        text=row["text"],
        audio_media_id=row["audio_media_id"],
        created_at=_require_dt(row["created_at"]),
    )


def row_to_right_now(row: sqlite3.Row) -> RightNowSnapshot:
    return RightNowSnapshot(
        id=RightNowId(row["id"]),
        family_id=FamilyId(row["family_id"]),
        child_id=ChildId(row["child_id"]),
        prompt=row["prompt"],
        answer=row["answer"],
        captured_at=_require_dt(row["captured_at"]),
    )


def row_to_voice_note(row: sqlite3.Row) -> VoiceNote:
    """A recording, and the transcript only if all five of its columns survived.

    Partial provenance is treated as no transcript rather than as a transcript with gaps.
    A row with words but no engine would render as something a person said, which is the
    one mistake this table is shaped to prevent (PRD 8.7).
    """
    return VoiceNote(
        media_id=MediaId(row["media_id"]),
        family_id=FamilyId(row["family_id"]),
        author_id=MemberId(row["author_id"]),
        duration_seconds=float(row["duration_seconds"]),
        recorded_at=_require_dt(row["recorded_at"]),
        transcript=_row_to_transcript(row),
    )


def _row_to_transcript(row: sqlite3.Row) -> Transcript | None:
    if not row["transcript_text"] or not row["transcript_engine"]:
        return None
    if row["transcript_source"] is None or row["transcript_confidence"] is None:
        return None
    return Transcript(
        text=row["transcript_text"],
        source=AttributionSource(row["transcript_source"]),
        confidence=Confidence(float(row["transcript_confidence"])),
        engine=row["transcript_engine"],
        made_at=_require_dt(row["transcript_made_at"]),
    )


def row_to_media(row: sqlite3.Row) -> MediaObject:
    return MediaObject(
        id=MediaId(row["id"]),
        family_id=FamilyId(row["family_id"]),
        kind=MediaKind(row["kind"]),
        mime_type=row["mime_type"],
        byte_size=row["byte_size"],
        content_hash=row["content_hash"],
        storage_key=row["storage_key"],
        encrypted=bool(row["encrypted"]),
        created_at=_require_dt(row["created_at"]),
    )


def rows_to_family(
    family_row: sqlite3.Row, member_rows: list[sqlite3.Row], child_rows: list[sqlite3.Row]
) -> Family:
    return Family(
        id=FamilyId(family_row["id"]),
        name=family_row["name"],
        members=tuple(
            Member(MemberId(r["id"]), r["display_name"], MemberRole(r["role"])) for r in member_rows
        ),
        children=tuple(
            ChildProfile(
                ChildId(r["id"]),
                MemberId(r["member_id"]),
                r["display_name"],
                date.fromisoformat(r["date_of_birth"]),
            )
            for r in child_rows
        ),
        created_at=_require_dt(family_row["created_at"]),
    )
