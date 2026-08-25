"""Family data rights (PRD 44, 45).

    "export everything; delete everything"

These are listed alongside encryption in the PRD's privacy principles, which means they
are load-bearing rather than a compliance checkbox. Two consequences shape this module:

* The export is meant to be **readable by the family**, not just machine-complete. If the
  product disappeared tomorrow, this JSON is what they would still have.
* The deletion is a **hard delete** including media bytes. A soft delete would make the
  promise false while appearing to keep it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from anuvritti.application.ports import (
    EventPublisher,
    FamilyRepository,
    LittleThingRepository,
    MediaStore,
    MomentRepository,
    RightNowRepository,
    SparkRepository,
    UnitOfWork,
    VoiceNoteRepository,
)
from anuvritti.domain.events import FamilyDataDeleted, FamilyDataExported
from anuvritti.domain.spark import Spark
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError
from anuvritti.shared.identity import FamilyId
from anuvritti.shared.result import Err, Ok, Result

EXPORT_FORMAT_VERSION = "1.0"


def spark_to_export(spark: Spark) -> dict[str, Any]:
    """A Spark as the family should see it - including how sure the machine was."""
    return {
        "id": str(spark.id),
        "title": spark.title,
        "note": spark.note,
        "saved_on": spark.created_at.date().isoformat(),
        "saved_by": str(spark.owner_id),
        "for_child": str(spark.subject_child_id) if spark.subject_child_id else None,
        "source": {
            "kind": spark.source.kind.value,
            "url": spark.source.url,
            "creator": spark.source.creator,
            "title": spark.source.title,
            "text": spark.source.text,
            "media_id": spark.source.media_id,
        },
        "intent": spark.intent.to_dict(),
        "category": spark.category.to_dict(),
        "age_range": spark.age_range.to_dict() if spark.age_range else None,
        "tags": list(spark.tags),
        "why": spark.why.to_dict() if spark.why else None,
        "status": spark.status.value,
        "visibility": spark.visibility.value,
    }


@dataclass(frozen=True, slots=True)
class ExportFamilyDataQuery:
    family_id: FamilyId


class ExportFamilyDataUseCase:
    """Everything this family ever gave us, in one readable document."""

    def __init__(
        self,
        *,
        families: FamilyRepository,
        sparks: SparkRepository,
        moments: MomentRepository,
        little_things: LittleThingRepository,
        right_now: RightNowRepository,
        voice_notes: VoiceNoteRepository,
        media: MediaStore,
        events: EventPublisher,
        clock: Clock,
    ) -> None:
        self._families = families
        self._sparks = sparks
        self._moments = moments
        self._little_things = little_things
        self._right_now = right_now
        self._voice_notes = voice_notes
        self._media = media
        self._events = events
        self._clock = clock

    def execute(self, query: ExportFamilyDataQuery) -> Result[dict[str, Any], DomainError]:
        family_result = self._families.get(query.family_id)
        if family_result.is_err():
            return Err(family_result.unwrap_err())
        family = family_result.unwrap()
        today = self._clock.today()

        sparks = self._sparks.list_for_family(query.family_id)
        if sparks.is_err():
            return Err(sparks.unwrap_err())
        moments = self._moments.list_for_family(query.family_id)
        if moments.is_err():
            return Err(moments.unwrap_err())
        little_things = self._little_things.list_for_family(query.family_id)
        if little_things.is_err():
            return Err(little_things.unwrap_err())
        right_now = self._right_now.list_for_family(query.family_id)
        if right_now.is_err():
            return Err(right_now.unwrap_err())
        voice_notes = self._voice_notes.list_for_family(query.family_id)
        if voice_notes.is_err():
            return Err(voice_notes.unwrap_err())
        media = self._media.list_for_family(query.family_id)
        if media.is_err():
            return Err(media.unwrap_err())

        archive: dict[str, Any] = {
            "format_version": EXPORT_FORMAT_VERSION,
            "exported_at": self._clock.now().isoformat(),
            "family": {
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
            },
            "sparks": [spark_to_export(s) for s in sparks.unwrap()],
            "moments": [
                {
                    "id": str(m.id),
                    "spark_id": str(m.spark_id),
                    "happened_on": m.happened_on.isoformat(),
                    "reflection": m.reflection,
                    "photo_media_id": m.photo_media_id,
                    "audio_media_id": m.audio_media_id,
                }
                for m in moments.unwrap()
            ],
            "little_things": [
                {
                    "id": str(t.id),
                    "text": t.text,
                    "audio_media_id": t.audio_media_id,
                    "captured_on": t.created_at.date().isoformat(),
                }
                for t in little_things.unwrap()
            ],
            "right_now": [
                {
                    "id": str(s.id),
                    "child_id": str(s.child_id),
                    "prompt": s.prompt,
                    "answer": s.answer,
                    "captured_on": s.captured_at.date().isoformat(),
                }
                for s in right_now.unwrap()
            ],
            # PRD 21. The recording is the artifact, so what the export carries is the
            # media id to fetch the bytes with - plus the transcript *and* who made it, so
            # that a family reading this file in twenty years can tell which sentences their
            # father said and which ones a program guessed at (PRD 8.7).
            "recordings": [
                {
                    "media_id": str(n.media_id),
                    "recorded_by": str(n.author_id),
                    "recorded_on": n.recorded_at.date().isoformat(),
                    "duration_seconds": n.duration_seconds,
                    "transcript": n.transcript.to_dict() if n.transcript else None,
                }
                for n in voice_notes.unwrap()
            ],
            # An index of the media, never the bytes. The bytes are downloaded separately
            # so an export never becomes a second, unencrypted copy of the archive.
            "media_manifest": [m.to_dict() for m in media.unwrap()],
        }

        self._events.publish(
            (
                FamilyDataExported(
                    aggregate_id=str(query.family_id),
                    occurred_at=self._clock.now(),
                    spark_count=len(archive["sparks"]),
                    media_count=len(archive["media_manifest"]),
                ),
            ),
            family_id=query.family_id,
        )
        return Ok(archive)


@dataclass(frozen=True, slots=True)
class DeleteFamilyDataCommand:
    family_id: FamilyId


class DeleteFamilyDataUseCase:
    """Erase a family. Completely, including the bytes on disk."""

    def __init__(
        self,
        *,
        families: FamilyRepository,
        sparks: SparkRepository,
        moments: MomentRepository,
        little_things: LittleThingRepository,
        right_now: RightNowRepository,
        voice_notes: VoiceNoteRepository,
        media: MediaStore,
        events: EventPublisher,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._families = families
        self._sparks = sparks
        self._moments = moments
        self._little_things = little_things
        self._right_now = right_now
        self._voice_notes = voice_notes
        self._media = media
        self._events = events
        self._clock = clock
        self._uow = uow

    def execute(self, command: DeleteFamilyDataCommand) -> Result[dict[str, int], DomainError]:
        exists = self._families.get(command.family_id)
        if exists.is_err():
            return Err(exists.unwrap_err())

        # Media first: if this fails, the catalogue still points at the bytes and the
        # deletion can be retried. Losing the index while keeping the files would leave
        # orphaned pictures of a child on disk with nothing to find them by.
        media_deleted = self._media.delete_for_family(command.family_id)
        if media_deleted.is_err():
            return Err(media_deleted.unwrap_err())

        counts: dict[str, int] = {"media": media_deleted.unwrap()}
        with self._uow:
            for name, repository in (
                ("moments", self._moments),
                ("sparks", self._sparks),
                ("little_things", self._little_things),
                ("right_now", self._right_now),
                ("recordings", self._voice_notes),
            ):
                deleted = repository.delete_for_family(command.family_id)
                if deleted.is_err():
                    self._uow.rollback()
                    return Err(deleted.unwrap_err())
                counts[name] = deleted.unwrap()

            family_deleted = self._families.delete(command.family_id)
            if family_deleted.is_err():
                self._uow.rollback()
                return Err(family_deleted.unwrap_err())
            counts["family"] = family_deleted.unwrap()
            self._uow.commit()

        # The audit trail is erased last and separately: it records that an erasure
        # happened, which is the one thing that must outlive the data (PRD 44).
        counts["events"] = self._events.delete_for_family(command.family_id)
        self._events.publish(
            (
                FamilyDataDeleted(
                    aggregate_id=str(command.family_id),
                    occurred_at=self._clock.now(),
                    deleted_counts=counts,
                ),
            ),
            family_id=command.family_id,
        )
        return Ok(counts)
