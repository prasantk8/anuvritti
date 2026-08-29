"""The application persists the server's measurement, never the phone's claim."""

from datetime import UTC, datetime

from anuvritti.application.voice import KeepVoiceNoteCommand, KeepVoiceNoteUseCase
from anuvritti.shared.clock import FrozenClock
from tests.support.fakes import (
    FAMILY,
    PAPA,
    FakeAudioDurationMeasurer,
    InMemoryFamilyRepository,
    InMemoryMediaStore,
    InMemoryVoiceNoteRepository,
    NullTranscriber,
    NullUnitOfWork,
    RecordingEventPublisher,
    build_family,
)


def test_a_phone_cannot_shorten_a_recording_by_under_reporting_it():
    now = datetime(2026, 1, 13, 21, 40, tzinfo=UTC)
    media = InMemoryMediaStore()
    stored = media.put(FAMILY, content=b"the whole recording", mime_type="audio/wav", at=now)
    measured = FakeAudioDurationMeasurer(8.75)
    notes = InMemoryVoiceNoteRepository()
    keep = KeepVoiceNoteUseCase(
        families=InMemoryFamilyRepository(build_family()),
        media=media,
        duration_measurer=measured,
        voice_notes=notes,
        transcriber=NullTranscriber(),
        events=RecordingEventPublisher(),
        clock=FrozenClock(now),
        uow=NullUnitOfWork(),
    )

    note = keep.execute(
        KeepVoiceNoteCommand(FAMILY, PAPA, stored.unwrap().id, duration_seconds=0.2)
    ).unwrap()

    assert note.duration_seconds == 8.75
    assert measured.seen == [(b"the whole recording", "audio/wav")]
