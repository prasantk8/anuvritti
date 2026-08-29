"""Import what already exists (TASK-908, PRD 9, PRD 47).

A Photos export, a WhatsApp chat, a Notes dump become Sparks and Moments with source
IMPORTED and their original historical dates, so the first film has a childhood in it and
not just a month.

Constitutional rule (PRD 47):
Nothing is inferred that the import did not carry. Every imported object preserves its
authentic provenance, original capture timestamps, and human statements.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from anuvritti.application.ports import (
    EventPublisher,
    FamilyRepository,
    LittleThingRepository,
    MediaStore,
    MomentRepository,
    SparkRepository,
    UnitOfWork,
)
from anuvritti.domain.moment import Moment
from anuvritti.domain.presence import LittleThing
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import (
    Attributed,
    IntentType,
    SourceRef,
    SparkStatus,
    Visibility,
)
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    IdGenerator,
    LittleThingId,
    MemberId,
    MomentId,
    SparkId,
)
from anuvritti.shared.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class PhotoImportItem:
    filename: str
    content: bytes
    mime_type: str
    taken_at: datetime
    description: str | None = None
    subject_child_id: ChildId | None = None


@dataclass(frozen=True, slots=True)
class NoteImportItem:
    text: str
    created_at: datetime
    title: str | None = None
    subject_child_id: ChildId | None = None


@dataclass(frozen=True, slots=True)
class ImportPhotosCommand:
    family_id: FamilyId
    actor_id: MemberId
    photos: Sequence[PhotoImportItem]
    default_child_id: ChildId | None = None


@dataclass(frozen=True, slots=True)
class ImportNotesCommand:
    family_id: FamilyId
    actor_id: MemberId
    notes: Sequence[NoteImportItem]
    default_child_id: ChildId | None = None


@dataclass(frozen=True, slots=True)
class ImportWhatsAppCommand:
    family_id: FamilyId
    actor_id: MemberId
    chat_text: str
    media_files: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    author_map: dict[str, MemberId] = field(default_factory=dict)
    default_child_id: ChildId | None = None


@dataclass(frozen=True, slots=True)
class ImportReport:
    sparks: tuple[Spark, ...] = ()
    moments: tuple[Moment, ...] = ()
    little_things: tuple[LittleThing, ...] = ()

    @property
    def total_imported(self) -> int:
        return len(self.sparks) + len(self.moments) + len(self.little_things)


# Regular expressions for WhatsApp export parsing
# Matches:
# 1) [DD/MM/YYYY, HH:MM:SS] Author: Message
# 2) [DD/MM/YY, HH:MM:SS AM/PM] Author: Message
# 3) DD/MM/YYYY, HH:MM - Author: Message
# 4) MM/DD/YY, HH:MM AM - Author: Message
_WA_LINE_RE = re.compile(
    r"^(?:\[(?P<date1>\d{1,4}[./-]\d{1,2}[./-]\d{1,4}),?\s+(?P<time1>\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?)\]|"
    r"(?P<date2>\d{1,4}[./-]\d{1,2}[./-]\d{1,4}),?\s+(?P<time2>\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?)\s+-\s+)"
    r"(?P<author>[^:]+?):\s+(?P<message>.*)$"
)

_ATTACHED_FILE_RE = re.compile(
    r"<attached:\s*(?P<filename>[^>]+)>"
    r"|(?P<filename2>[\w\-.]+\.(?:jpg|jpeg|png|heic|mp4|m4a|aac|opus|webp))\s+\(file attached\)",
    re.IGNORECASE,
)


def _parse_wa_datetime(date_str: str, time_str: str) -> datetime:
    """Parse WhatsApp localized date-time into a UTC-aware datetime."""
    date_str = date_str.replace(".", "/").replace("-", "/")
    parts = [int(p) for p in date_str.split("/")]

    # Disambiguate day/month/year
    if parts[0] > 1000:
        year, month, day = parts[0], parts[1], parts[2]
    elif parts[2] > 1000:
        day, month, year = parts[0], parts[1], parts[2]
    elif parts[2] < 100:
        year = 2000 + parts[2]
        # Common export convention: day first if > 12
        if parts[0] > 12:
            day, month = parts[0], parts[1]
        elif parts[1] > 12:
            month, day = parts[0], parts[1]
        else:
            day, month = parts[0], parts[1]
    else:
        day, month, year = parts[0], parts[1], parts[2]

    time_str = time_str.strip().upper()
    is_pm = "PM" in time_str
    is_am = "AM" in time_str
    clean_time = time_str.replace("AM", "").replace("PM", "").strip()
    time_parts = [int(p) for p in clean_time.split(":")]
    hour = time_parts[0]
    minute = time_parts[1]
    second = time_parts[2] if len(time_parts) > 2 else 0

    if is_pm and hour < 12:
        hour += 12
    elif is_am and hour == 12:
        hour = 0

    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


class ImportUseCase:
    """Imports historical family archives with strict provenance preservation."""

    def __init__(
        self,
        *,
        families: FamilyRepository,
        sparks: SparkRepository,
        moments: MomentRepository,
        little_things: LittleThingRepository,
        media: MediaStore,
        events: EventPublisher,
        ids: IdGenerator,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._families = families
        self._sparks = sparks
        self._moments = moments
        self._little_things = little_things
        self._media = media
        self._events = events
        self._ids = ids
        self._clock = clock
        self._uow = uow

    def import_photos(self, command: ImportPhotosCommand) -> Result[ImportReport, DomainError]:
        family = self._families.get(command.family_id)
        if family.is_err():
            return Err(family.unwrap_err())

        imported_sparks: list[Spark] = []
        imported_moments: list[Moment] = []

        with self._uow:
            for item in command.photos:
                # 1. Put into media store
                media_res = self._media.put(
                    command.family_id,
                    content=item.content,
                    mime_type=item.mime_type,
                    at=item.taken_at,
                )
                if media_res.is_err():
                    return Err(media_res.unwrap_err())
                photo_obj = media_res.unwrap()

                # 2. Create Spark with SourceKind.IMPORTED
                spark_id = SparkId(self._ids.new_id())
                child_id = item.subject_child_id or command.default_child_id
                source = SourceRef.from_imported(
                    title=item.filename,
                    text=item.description,
                    media_id=str(photo_obj.id),
                )

                spark = Spark(
                    id=spark_id,
                    family_id=command.family_id,
                    owner_id=command.actor_id,
                    subject_child_id=child_id,
                    title=item.filename,
                    note=item.description,
                    source=source,
                    intent=Attributed.stated(IntentType.REMEMBER),
                    category=Attributed.stated("photo"),
                    age_range=None,
                    tags=("imported", "photo"),
                    why=None,
                    status=SparkStatus.EXPERIENCED,
                    visibility=Visibility.FAMILY,
                    suggested_count=0,
                    last_suggested_at=None,
                    snoozed_until=None,
                    created_at=item.taken_at,
                    updated_at=item.taken_at,
                )
                self._sparks.save(spark)
                imported_sparks.append(spark)

                # 3. Create Moment
                moment_id = MomentId(self._ids.new_id())
                moment_res = Moment.create(
                    moment_id=moment_id,
                    family_id=command.family_id,
                    spark_id=spark_id,
                    created_by=command.actor_id,
                    spark_captured_at=item.taken_at,
                    at=item.taken_at,
                    happened_on=item.taken_at.date(),
                    reflection=item.description,
                    photo_media_id=str(photo_obj.id),
                )
                if moment_res.is_err():
                    return Err(moment_res.unwrap_err())
                moment = moment_res.unwrap()
                self._moments.save(moment)
                imported_moments.append(moment)

            self._uow.commit()

        return Ok(
            ImportReport(
                sparks=tuple(imported_sparks),
                moments=tuple(imported_moments),
                little_things=(),
            )
        )

    def import_notes(self, command: ImportNotesCommand) -> Result[ImportReport, DomainError]:
        family = self._families.get(command.family_id)
        if family.is_err():
            return Err(family.unwrap_err())

        imported_sparks: list[Spark] = []

        with self._uow:
            for item in command.notes:
                lines = [line.strip() for line in item.text.splitlines() if line.strip()]
                title = item.title or (lines[0] if lines else "Note")
                body = item.text

                spark_id = SparkId(self._ids.new_id())
                child_id = item.subject_child_id or command.default_child_id
                source = SourceRef.from_imported(title=title, text=body)

                spark = Spark(
                    id=spark_id,
                    family_id=command.family_id,
                    owner_id=command.actor_id,
                    subject_child_id=child_id,
                    title=title[:80],
                    note=body,
                    source=source,
                    intent=Attributed.stated(IntentType.REMEMBER),
                    category=Attributed.stated("note"),
                    age_range=None,
                    tags=("imported", "note"),
                    why=None,
                    status=SparkStatus.WAITING,
                    visibility=Visibility.FAMILY,
                    suggested_count=0,
                    last_suggested_at=None,
                    snoozed_until=None,
                    created_at=item.created_at,
                    updated_at=item.created_at,
                )
                self._sparks.save(spark)
                imported_sparks.append(spark)

            self._uow.commit()

        return Ok(
            ImportReport(
                sparks=tuple(imported_sparks),
                moments=(),
                little_things=(),
            )
        )

    def import_whatsapp(self, command: ImportWhatsAppCommand) -> Result[ImportReport, DomainError]:
        family = self._families.get(command.family_id)
        if family.is_err():
            return Err(family.unwrap_err())

        imported_sparks: list[Spark] = []
        imported_moments: list[Moment] = []
        imported_little_things: list[LittleThing] = []

        lines = command.chat_text.splitlines()
        with self._uow:
            for raw_line in lines:
                line = raw_line.strip()
                if not line:
                    continue

                match = _WA_LINE_RE.match(line)
                if not match:
                    continue

                gd = match.groupdict()
                date_part = gd["date1"] or gd["date2"]
                time_part = gd["time1"] or gd["time2"]
                author_name = gd["author"].strip()
                message = gd["message"].strip()

                msg_time = _parse_wa_datetime(date_part, time_part)
                author_id = command.author_map.get(author_name, command.actor_id)
                child_id = command.default_child_id

                # Check if there is an attachment
                attach_match = _ATTACHED_FILE_RE.search(message)
                photo_media_id: str | None = None

                if attach_match:
                    filename = (
                        attach_match.group("filename") or attach_match.group("filename2") or ""
                    ).strip()
                    if filename in command.media_files:
                        file_bytes, mime_type = command.media_files[filename]
                        media_res = self._media.put(
                            command.family_id,
                            content=file_bytes,
                            mime_type=mime_type,
                            at=msg_time,
                        )
                        if media_res.is_ok():
                            photo_media_id = str(media_res.unwrap().id)

                if photo_media_id:
                    # Moment + Spark
                    clean_text = _ATTACHED_FILE_RE.sub("", message).strip() or None
                    spark_id = SparkId(self._ids.new_id())
                    source = SourceRef.from_imported(
                        title=clean_text or "WhatsApp Photo",
                        text=clean_text,
                        creator=author_name,
                        media_id=photo_media_id,
                    )
                    spark = Spark(
                        id=spark_id,
                        family_id=command.family_id,
                        owner_id=author_id,
                        subject_child_id=child_id,
                        title=source.display_title(),
                        note=clean_text,
                        source=source,
                        intent=Attributed.stated(IntentType.REMEMBER),
                        category=Attributed.stated("chat"),
                        age_range=None,
                        tags=("imported", "whatsapp"),
                        why=None,
                        status=SparkStatus.EXPERIENCED,
                        visibility=Visibility.FAMILY,
                        suggested_count=0,
                        last_suggested_at=None,
                        snoozed_until=None,
                        created_at=msg_time,
                        updated_at=msg_time,
                    )
                    self._sparks.save(spark)
                    imported_sparks.append(spark)

                    moment_id = MomentId(self._ids.new_id())
                    moment_res = Moment.create(
                        moment_id=moment_id,
                        family_id=command.family_id,
                        spark_id=spark_id,
                        created_by=author_id,
                        spark_captured_at=msg_time,
                        at=msg_time,
                        happened_on=msg_time.date(),
                        reflection=clean_text,
                        photo_media_id=photo_media_id,
                    )
                    if moment_res.is_ok():
                        moment = moment_res.unwrap()
                        self._moments.save(moment)
                        imported_moments.append(moment)
                else:
                    # Pure text message -> LittleThing
                    if message:
                        lt_id = LittleThingId(self._ids.new_id())
                        lt_res = LittleThing.capture(
                            little_thing_id=lt_id,
                            family_id=command.family_id,
                            author_id=author_id,
                            at=msg_time,
                            subject_child_id=child_id,
                            text=f"[{author_name}]: {message}",
                        )
                        if lt_res.is_ok():
                            lt = lt_res.unwrap()
                            self._little_things.save(lt)
                            imported_little_things.append(lt)

            self._uow.commit()

        return Ok(
            ImportReport(
                sparks=tuple(imported_sparks),
                moments=tuple(imported_moments),
                little_things=tuple(imported_little_things),
            )
        )
