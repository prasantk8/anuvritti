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
    LexiconRepository,
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
from anuvritti.domain.values import MemberRole, Visibility
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, MemberId, SparkId
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
        lexicon: LexiconRepository,
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
        self._lexicon = lexicon

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
        lexicon = self._lexicon.load(query.family_id)
        if lexicon.is_err():
            return Err(lexicon.unwrap_err())

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
            # What this family's words mean to this family, which is the only place that
            # is written down (PRD 44: export everything).
            "lexicon": lexicon.unwrap().to_dict(),
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
        lexicon: LexiconRepository,
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
        self._lexicon = lexicon

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
                # A family's own words go with the family. A lexicon left behind would be
                # the one thing that survived "delete everything" (PRD 44).
                ("lexicon", self._lexicon),
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


# ------------------------------------------------------------------ Child Rights (PRD 45, PRD 25)
@dataclass(frozen=True, slots=True)
class HideChildContentCommand:
    family_id: FamilyId
    child_id: ChildId
    spark_id: SparkId
    requestor_id: MemberId


class HideChildContentUseCase:
    """PRD 45 - The child (or parent on their behalf) can hide any spark about them."""

    def __init__(
        self,
        *,
        families: FamilyRepository,
        sparks: SparkRepository,
        events: EventPublisher,
        uow: UnitOfWork,
    ) -> None:
        self._families = families
        self._sparks = sparks
        self._events = events
        self._uow = uow

    def execute(self, command: HideChildContentCommand) -> Result[Spark, DomainError]:
        family_res = self._families.get(command.family_id)
        if family_res.is_err():
            return Err(family_res.unwrap_err())
        family = family_res.unwrap()

        child_res = family.child(command.child_id)
        if child_res.is_err():
            return Err(child_res.unwrap_err())

        member_res = family.member(command.requestor_id)
        if member_res.is_err():
            return Err(member_res.unwrap_err())
        member = member_res.unwrap()

        # Authorization: either the child themselves or a parent
        if member.role not in (MemberRole.CHILD, MemberRole.PARENT, MemberRole.CO_PARENT):
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    f"member {command.requestor_id} cannot hide content for child",
                )
            )

        spark_res = self._sparks.get(command.spark_id)
        if spark_res.is_err():
            return Err(spark_res.unwrap_err())
        spark = spark_res.unwrap()

        if spark.family_id != command.family_id:
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    "spark belongs to a different family",
                )
            )

        # Set visibility to PRIVATE so it disappears from family view and films
        hidden = spark.change_visibility(Visibility.PRIVATE)
        if hidden.is_err():
            return Err(hidden.unwrap_err())
        updated_spark = hidden.unwrap()

        with self._uow:
            saved = self._sparks.save(updated_spark)
            if saved.is_err():
                self._uow.rollback()
                return Err(saved.unwrap_err())
            self._events.publish(updated_spark.pending_events, family_id=command.family_id)
            self._uow.commit()

        return Ok(updated_spark)


@dataclass(frozen=True, slots=True)
class DeleteChildContentCommand:
    family_id: FamilyId
    child_id: ChildId
    spark_id: SparkId
    requestor_id: MemberId


class DeleteChildContentUseCase:
    """PRD 45 - The child can permanently delete any spark/moment about them."""

    def __init__(
        self,
        *,
        families: FamilyRepository,
        sparks: SparkRepository,
        moments: MomentRepository,
        events: EventPublisher,
        uow: UnitOfWork,
    ) -> None:
        self._families = families
        self._sparks = sparks
        self._moments = moments
        self._events = events
        self._uow = uow

    def execute(self, command: DeleteChildContentCommand) -> Result[None, DomainError]:
        family_res = self._families.get(command.family_id)
        if family_res.is_err():
            return Err(family_res.unwrap_err())
        family = family_res.unwrap()

        child_res = family.child(command.child_id)
        if child_res.is_err():
            return Err(child_res.unwrap_err())

        member_res = family.member(command.requestor_id)
        if member_res.is_err():
            return Err(member_res.unwrap_err())
        member = member_res.unwrap()

        if member.role not in (MemberRole.CHILD, MemberRole.PARENT, MemberRole.CO_PARENT):
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    f"member {command.requestor_id} cannot delete content for child",
                )
            )

        spark_res = self._sparks.get(command.spark_id)
        if spark_res.is_err():
            return Err(spark_res.unwrap_err())
        spark = spark_res.unwrap()

        if spark.family_id != command.family_id:
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    "spark belongs to a different family",
                )
            )

        with self._uow:
            # A Spark that was brought back has a Moment hanging off it. Erasing the Spark
            # and leaving the Moment would leave a memory whose origin no longer exists.
            moment_res = self._moments.find_by_spark(command.spark_id)
            if moment_res.is_err():
                self._uow.rollback()
                return Err(moment_res.unwrap_err())
            moment = moment_res.unwrap()
            if moment is not None:
                removed = self._moments.delete(moment.id)
                if removed.is_err():
                    self._uow.rollback()
                    return Err(removed.unwrap_err())

            deleted = self._sparks.delete(command.spark_id)
            if deleted.is_err():
                self._uow.rollback()
                return Err(deleted.unwrap_err())
            self._uow.commit()

        return Ok(None)


@dataclass(frozen=True, slots=True)
class ExportChildVaultQuery:
    family_id: FamilyId
    child_id: ChildId
    requestor_id: MemberId


class ExportChildVaultUseCase:
    """PRD 45 - The child can own the whole record later: export personal sub-vault."""

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

    def execute(self, query: ExportChildVaultQuery) -> Result[dict[str, Any], DomainError]:
        family_res = self._families.get(query.family_id)
        if family_res.is_err():
            return Err(family_res.unwrap_err())
        family = family_res.unwrap()

        child_res = family.child(query.child_id)
        if child_res.is_err():
            return Err(child_res.unwrap_err())
        child = child_res.unwrap()

        member_res = family.member(query.requestor_id)
        if member_res.is_err():
            return Err(member_res.unwrap_err())
        member = member_res.unwrap()

        if member.role not in (MemberRole.CHILD, MemberRole.PARENT, MemberRole.CO_PARENT):
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    f"member {query.requestor_id} cannot export vault for child",
                )
            )

        today = self._clock.today()

        # 1. Filter sparks for this child
        all_sparks = self._sparks.list_for_family(query.family_id)
        if all_sparks.is_err():
            return Err(all_sparks.unwrap_err())
        child_sparks = [s for s in all_sparks.unwrap() if s.subject_child_id == query.child_id]
        child_spark_ids = {s.id for s in child_sparks}

        # 2. Filter moments for this child's sparks
        all_moments = self._moments.list_for_family(query.family_id)
        if all_moments.is_err():
            return Err(all_moments.unwrap_err())
        child_moments = [m for m in all_moments.unwrap() if m.spark_id in child_spark_ids]

        # 3. Filter little things for this child
        all_things = self._little_things.list_for_family(query.family_id)
        if all_things.is_err():
            return Err(all_things.unwrap_err())
        child_things = [t for t in all_things.unwrap() if t.subject_child_id == query.child_id]

        # 4. Filter right now snapshots for this child
        all_rn = self._right_now.list_for_family(query.family_id)
        if all_rn.is_err():
            return Err(all_rn.unwrap_err())
        child_rn = [s for s in all_rn.unwrap() if s.child_id == query.child_id]

        # 5. Media manifest
        all_media = self._media.list_for_family(query.family_id)
        if all_media.is_err():
            return Err(all_media.unwrap_err())

        vault: dict[str, Any] = {
            "format_version": EXPORT_FORMAT_VERSION,
            "exported_at": self._clock.now().isoformat(),
            "vault_owner_child": {
                "id": str(child.id),
                "display_name": child.display_name,
                "date_of_birth": child.date_of_birth.isoformat(),
                "age_years": child.age_years(today),
            },
            "sparks": [spark_to_export(s) for s in child_sparks],
            "moments": [
                {
                    "id": str(m.id),
                    "spark_id": str(m.spark_id),
                    "happened_on": m.happened_on.isoformat(),
                    "reflection": m.reflection,
                    "photo_media_id": m.photo_media_id,
                    "audio_media_id": m.audio_media_id,
                }
                for m in child_moments
            ],
            "little_things": [
                {
                    "id": str(t.id),
                    "text": t.text,
                    "audio_media_id": t.audio_media_id,
                    "captured_on": t.created_at.date().isoformat(),
                }
                for t in child_things
            ],
            "right_now": [
                {
                    "id": str(s.id),
                    "prompt": s.prompt,
                    "answer": s.answer,
                    "captured_on": s.captured_at.date().isoformat(),
                }
                for s in child_rn
            ],
            "media_manifest": [m.to_dict() for m in all_media.unwrap()],
        }

        return Ok(vault)
