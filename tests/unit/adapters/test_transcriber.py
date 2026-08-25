"""TASK-603 - the Transcriber port and the adapter that cannot phone home.

`tests/constitution/test_no_public_model.py` holds the structural half of this: no module
under `anuvritti.adapters` may reach a network module, checked by walking the import graph.
This file holds the behavioural half - what the adapter does with the bytes it is given,
and what it refuses to do.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.adapters.transcription.local import (
    MAX_CONFIDENCE,
    Heard,
    LocalTranscriber,
    SilentTranscriber,
    SpeechModel,
)
from anuvritti.domain.values import AttributionSource
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import FamilyId, MediaId
from tests.support.fakes import InMemoryMediaStore

NOW = datetime(2026, 1, 13, 21, 40, tzinfo=UTC)
FAMILY = FamilyId("fam-1")
CLIP = b"\x00\x00\x00\x20ftypM4A " + b"his voice" * 40


class Whisperish:
    """A local model that hears one fixed thing, and counts how often it was asked."""

    def __init__(self, heard: Heard | None = None) -> None:
        self.heard = heard or Heard("he called the elevator an alligator", 0.72)
        self.calls: list[tuple[int, str]] = []

    @property
    def name(self) -> str:
        return "whisper.cpp-tiny"

    def listen(self, audio: bytes, *, mime_type: str) -> Heard | None:
        self.calls.append((len(audio), mime_type))
        return self.heard


@pytest.fixture
def media():
    return InMemoryMediaStore()


def an_audio_id(store) -> MediaId:
    return store.put(FAMILY, content=CLIP, mime_type="audio/m4a", at=NOW).unwrap().id


class TestTheDefaultIsToKeepAndNotIndex:
    def test_the_silent_transcriber_returns_nothing_and_that_is_a_real_answer(self):
        assert SilentTranscriber().transcribe(MediaId("med-1")).unwrap() is None

    def test_a_local_transcriber_with_no_model_installed_returns_nothing(self, media):
        """Not a failure. The shipping configuration for a box in someone's house."""
        transcriber = LocalTranscriber(media=media, model=None, clock=FrozenClock(NOW))
        assert transcriber.transcribe(an_audio_id(media)).unwrap() is None

    def test_no_model_means_the_bytes_are_never_even_read(self, media):
        """The stronger version of the same statement: not sent, and not fetched either."""
        audio_id = an_audio_id(media)
        reads: list[str] = []
        original = media.get
        media.get = lambda mid: (reads.append(str(mid)), original(mid))[1]  # type: ignore[method-assign]

        LocalTranscriber(media=media, model=None, clock=FrozenClock(NOW)).transcribe(audio_id)
        assert reads == []


class TestWhatAModelIsGiven:
    def test_it_receives_bytes_and_a_mime_type_and_nothing_else(self, media):
        """The narrowness of `SpeechModel.listen` is the privacy guarantee.

        No media id, no store, no session, no config, no URL. A model behind this port can
        still do something foolish with the bytes, but it cannot be handed the address of
        anywhere to send them.
        """
        model = Whisperish()
        LocalTranscriber(media=media, model=model, clock=FrozenClock(NOW)).transcribe(
            an_audio_id(media)
        )
        assert model.calls == [(len(CLIP), "audio/m4a")]

    def test_the_port_signature_admits_no_destination(self):
        import inspect

        parameters = set(inspect.signature(SpeechModel.listen).parameters)
        assert parameters == {"self", "audio", "mime_type"}


class TestWhatComesBack:
    def test_a_reading_carries_the_engine_that_made_it(self, media):
        transcript = (
            LocalTranscriber(media=media, model=Whisperish(), clock=FrozenClock(NOW))
            .transcribe(an_audio_id(media))
            .unwrap()
        )
        assert transcript is not None
        assert transcript.engine == "whisper.cpp-tiny"
        assert transcript.source is AttributionSource.AI
        assert transcript.made_at == NOW

    def test_a_model_that_reports_certainty_is_written_down_lower_rather_than_discarded(
        self, media
    ):
        """PRD 8.7. Clamped, not rejected - what it heard is still worth keeping."""
        model = Whisperish(Heard("perfectly clear", 1.0))
        transcript = (
            LocalTranscriber(media=media, model=model, clock=FrozenClock(NOW))
            .transcribe(an_audio_id(media))
            .unwrap()
        )
        assert transcript is not None
        assert transcript.text == "perfectly clear"
        assert transcript.confidence.value == MAX_CONFIDENCE

    @pytest.mark.parametrize("nothing", [None, Heard("", 0.5), Heard("   ", 0.5)])
    def test_a_model_that_made_nothing_of_it_is_an_ordinary_outcome(self, media, nothing):
        """A four-second clip recorded next to a running tap. Kept, and unindexed."""
        model = Whisperish()
        model.heard = nothing
        result = LocalTranscriber(media=media, model=model, clock=FrozenClock(NOW)).transcribe(
            an_audio_id(media)
        )
        assert result.is_ok()
        assert result.unwrap() is None


class TestWhatItRefuses:
    def test_an_image_is_not_transcribable(self, media):
        photo = media.put(
            FAMILY, content=b"\xff\xd8\xff\xe0" + b"face" * 40, mime_type="image/jpeg", at=NOW
        ).unwrap()
        failed = LocalTranscriber(
            media=media, model=Whisperish(), clock=FrozenClock(NOW)
        ).transcribe(photo.id)
        assert failed.unwrap_err().code is ErrorCode.MEDIA_KIND_UNSUPPORTED

    def test_an_unknown_media_id_fails_before_a_model_is_woken_up(self, media):
        model = Whisperish()
        failed = LocalTranscriber(media=media, model=model, clock=FrozenClock(NOW)).transcribe(
            MediaId("med-nope")
        )
        assert failed.is_err()
        assert model.calls == []
