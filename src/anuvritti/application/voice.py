"""Keeping recordings, and the Papa Voice Vault (PRD 12, 17, 21, 24).

Three rules live here, and each one is a place where the obvious implementation is wrong.

**Transcription may never fail a save.** The transcriber runs after the recording is
safe, and its errors are swallowed on purpose. A parent who held a button for four seconds
in a moving car has already done the only irreversible part; failing that request because
a model was busy would lose the thing and keep the machinery.

**A transcript the phone brought with it is still a machine's reading.** iOS and Android
can both transcribe on-device, and it is a good idea to let them - it is faster and the
audio never leaves the handset. But the words that arrive are the phone's guess, not the
parent's statement, and they are stored with `AI` provenance for exactly that reason
(PRD 8.7). The only way to get a `HUMAN` transcript is `CorrectTranscriptUseCase`, which
requires a person to have actually read it.

**The vault is an archive, not an inbox.** `ListVoiceNotesUseCase` returns recordings,
newest first, and no count of them. There is no unread state, no "since you last looked",
and nothing on this path can be turned into a badge.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from anuvritti.application.ports import (
    EventPublisher,
    FamilyRepository,
    MediaStore,
    Transcriber,
    UnitOfWork,
    VoiceNoteRepository,
)
from anuvritti.domain.media import MediaKind
from anuvritti.domain.values import Confidence
from anuvritti.domain.voice import Transcript, VoiceNote
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId, MediaId, MemberId
from anuvritti.shared.result import Err, Ok, Result

#: What a transcript that came from the handset's own recogniser is called. It is a real
#: engine name rather than "device", because in five years someone will want to know which
#: reading came from which thing, and "device" will not answer that.
ON_DEVICE_ENGINE = "device-speech"

#: Where a phone-supplied confidence lands when the phone did not supply one. Deliberately
#: below `Confidence.LOW`, so an unlabelled reading renders as a question by default.
_ASSUMED_CONFIDENCE = 0.4

#: Never certainty. That belongs to the person who was in the room (PRD 8.7).
_CEILING = 0.85


@dataclass(frozen=True, slots=True)
class KeepVoiceNoteCommand:
    """`heard_*` is what the handset's own recogniser made of it, if anything."""

    family_id: FamilyId
    author_id: MemberId
    media_id: MediaId
    duration_seconds: float
    heard_text: str | None = None
    heard_confidence: float | None = None


class KeepVoiceNoteUseCase:
    """PRD 24 - the recording is kept. Everything else on this path is optional."""

    def __init__(
        self,
        *,
        families: FamilyRepository,
        media: MediaStore,
        voice_notes: VoiceNoteRepository,
        transcriber: Transcriber,
        events: EventPublisher,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._families = families
        self._media = media
        self._voice_notes = voice_notes
        self._transcriber = transcriber
        self._events = events
        self._clock = clock
        self._uow = uow

    def execute(self, command: KeepVoiceNoteCommand) -> Result[VoiceNote, DomainError]:
        family_result = self._families.get(command.family_id)
        if family_result.is_err():
            return Err(family_result.unwrap_err())

        member = family_result.unwrap().member(command.author_id)
        if member.is_err():
            return Err(member.unwrap_err())

        audio = self._audio_in_family(command.media_id, command.family_id)
        if audio.is_err():
            return Err(audio.unwrap_err())

        now = self._clock.now()
        kept = VoiceNote.kept(
            media_id=command.media_id,
            family_id=command.family_id,
            author_id=command.author_id,
            duration_seconds=command.duration_seconds,
            at=now,
        )
        if kept.is_err():
            return Err(kept.unwrap_err())

        note = self._indexed(kept.unwrap(), command)

        with self._uow:
            saved = self._voice_notes.save(note)
            if saved.is_err():
                self._uow.rollback()
                return Err(saved.unwrap_err())
            self._events.publish(note.pending_events, family_id=command.family_id)
            self._uow.commit()
        return Ok(note)

    def _audio_in_family(self, media_id: MediaId, family_id: FamilyId) -> Result[None, DomainError]:
        described = self._media.describe(media_id)
        if described.is_err():
            return Err(described.unwrap_err())
        media = described.unwrap()
        if media.family_id != family_id:
            # The same answer an unknown id gets. A different one would confirm that some
            # other family's recording exists at this address.
            return Err(DomainError(ErrorCode.MEDIA_NOT_FOUND, "no such media"))
        if media.kind is not MediaKind.AUDIO:
            return Err(
                DomainError(
                    ErrorCode.MEDIA_KIND_UNSUPPORTED,
                    "a voice note has to be audio",
                    {"kind": media.kind.value},
                )
            )
        return Ok(None)

    def _indexed(self, note: VoiceNote, command: KeepVoiceNoteCommand) -> VoiceNote:
        """Attach whatever reading is available, and never fail because none is.

        The phone's own reading wins when it exists: it was made with the audio still in
        memory on the device that recorded it, which is both faster and more private than
        anything this box can do afterwards.
        """
        from_phone = self._what_the_phone_heard(command)
        if from_phone is not None:
            return note.indexed_by(from_phone)

        read = self._transcriber.transcribe(note.media_id)
        if read.is_err():
            # Swallowed on purpose. An index that could not be built is not a reason to
            # lose a recording, and there is nothing here worth telling a parent about.
            return note
        transcript = read.unwrap()
        return note if transcript is None else note.indexed_by(transcript)

    def _what_the_phone_heard(self, command: KeepVoiceNoteCommand) -> Transcript | None:
        if not command.heard_text or not command.heard_text.strip():
            return None
        stated = command.heard_confidence
        confidence = _ASSUMED_CONFIDENCE if stated is None else min(max(stated, 0.0), _CEILING)
        heard = Transcript.machine(
            command.heard_text,
            confidence=Confidence(confidence),
            engine=ON_DEVICE_ENGINE,
            at=self._clock.now(),
        )
        return heard.unwrap() if heard.is_ok() else None


@dataclass(frozen=True, slots=True)
class CorrectTranscriptCommand:
    family_id: FamilyId
    media_id: MediaId
    text: str


class CorrectTranscriptUseCase:
    """A parent fixes what the machine misheard. Permanent, and the audio is untouched.

    This is the only door to a `HUMAN` transcript in the whole system, and it is a door a
    person has to walk through: nothing automatic can produce one.
    """

    def __init__(
        self,
        *,
        voice_notes: VoiceNoteRepository,
        events: EventPublisher,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._voice_notes = voice_notes
        self._events = events
        self._clock = clock
        self._uow = uow

    def execute(self, command: CorrectTranscriptCommand) -> Result[VoiceNote, DomainError]:
        found = self._voice_notes.get(command.media_id)
        if found.is_err():
            return Err(found.unwrap_err())

        note = found.unwrap()
        if note.family_id != command.family_id:
            return Err(DomainError(ErrorCode.MEDIA_NOT_FOUND, "no such recording"))

        corrected = note.corrected_to(command.text, at=self._clock.now())
        if corrected.is_err():
            return Err(corrected.unwrap_err())

        updated = corrected.unwrap()
        with self._uow:
            saved = self._voice_notes.save(updated)
            if saved.is_err():
                self._uow.rollback()
                return Err(saved.unwrap_err())
            self._events.publish(updated.pending_events, family_id=command.family_id)
            self._uow.commit()
        return Ok(updated)


@dataclass(frozen=True, slots=True)
class ListVoiceNotesQuery:
    family_id: FamilyId


class ListVoiceNotesUseCase:
    """The Papa Voice Vault (PRD 21).

    Everything the family ever recorded, newest first. No paging, no unread state and no
    count: this is a shelf, and a shelf does not tell you how far behind you are.
    """

    def __init__(self, *, voice_notes: VoiceNoteRepository) -> None:
        self._voice_notes = voice_notes

    def execute(self, query: ListVoiceNotesQuery) -> Result[Sequence[VoiceNote], DomainError]:
        return self._voice_notes.list_for_family(query.family_id)


@dataclass(frozen=True, slots=True)
class GetVoiceNoteQuery:
    family_id: FamilyId
    media_id: MediaId


class GetVoiceNoteUseCase:
    def __init__(self, *, voice_notes: VoiceNoteRepository) -> None:
        self._voice_notes = voice_notes

    def execute(self, query: GetVoiceNoteQuery) -> Result[VoiceNote, DomainError]:
        found = self._voice_notes.get(query.media_id)
        if found.is_err():
            return Err(found.unwrap_err())
        note = found.unwrap()
        if note.family_id != query.family_id:
            return Err(DomainError(ErrorCode.MEDIA_NOT_FOUND, "no such recording"))
        return Ok(note)
