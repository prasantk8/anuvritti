"""TASK-603 - the recording is the artifact and the transcript is only an index.

Every test in this file is one of the two rules stated in `domain/voice.py`, written as
the thing that would go wrong if the rule were dropped. They are worth reading as a list:
nothing is rejected for being short, a transcript cannot exist without its audio, and a
machine never gets to overwrite what a person said.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from anuvritti.domain.events import VoiceNoteIndexed, VoiceNoteKept
from anuvritti.domain.values import AttributionSource, Confidence
from anuvritti.domain.voice import (
    BY_HAND,
    MAX_DURATION_SECONDS,
    Transcript,
    VoiceNote,
)
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import FamilyId, MediaId, MemberId

NOW = datetime(2026, 1, 13, 21, 40, tzinfo=UTC)
LATER = datetime(2026, 1, 13, 21, 45, tzinfo=UTC)
FAMILY = FamilyId("fam-1")
PAPA = MemberId("mem-papa")
AUDIO = MediaId("med-1")


def a_note(duration: float = 4.2) -> VoiceNote:
    return VoiceNote.kept(
        media_id=AUDIO,
        family_id=FAMILY,
        author_id=PAPA,
        duration_seconds=duration,
        at=NOW,
    ).unwrap()


def machine(text: str = "he called the elevator an alligator", confidence: float = 0.7):
    return Transcript.machine(
        text, confidence=Confidence(confidence), engine="whisper.cpp-tiny", at=NOW
    ).unwrap()


class TestNothingIsTooShort:
    """PRD 24 - preserve imperfection. There is no bar to clear."""

    @pytest.mark.parametrize("duration", [0.0, 0.2, 0.4, 1.0, 4.2, 300.0, MAX_DURATION_SECONDS])
    def test_every_real_length_is_kept(self, duration):
        assert a_note(duration).duration_seconds == duration

    def test_half_a_second_of_someone_giving_up_is_a_recording(self):
        """The case the whole rule exists for.

        A parent starts to say something, stops, and lets go of the button. Every product
        instinct says to discard that. In ten years it may be the more interesting half.
        """
        note = a_note(0.4)
        assert note.duration_seconds == 0.4
        assert note.pending_events == (VoiceNoteKept(aggregate_id="med-1", occurred_at=NOW),)

    def test_silence_is_still_a_recording(self):
        assert a_note(3.0).is_indexed is False

    def test_a_negative_duration_is_refused_because_it_is_not_a_length(self):
        failed = VoiceNote.kept(
            media_id=AUDIO, family_id=FAMILY, author_id=PAPA, duration_seconds=-1.0, at=NOW
        )
        assert failed.unwrap_err().code is ErrorCode.VALIDATION_FAILED

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_arithmetic_accidents_are_refused(self, bad):
        failed = VoiceNote.kept(
            media_id=AUDIO, family_id=FAMILY, author_id=PAPA, duration_seconds=bad, at=NOW
        )
        assert failed.is_err()

    def test_something_longer_than_an_afternoon_is_refused_as_a_client_bug(self):
        failed = VoiceNote.kept(
            media_id=AUDIO,
            family_id=FAMILY,
            author_id=PAPA,
            duration_seconds=MAX_DURATION_SECONDS + 1,
            at=NOW,
        )
        assert failed.unwrap_err().details["max_duration_seconds"] == MAX_DURATION_SECONDS


class TestTheRecordingIsTheArtifact:
    def test_a_note_cannot_be_made_without_audio(self):
        """The strongest statement this module makes, and it is made by the type system.

        `media_id` is the identity and it is not optional, so there is no way to construct
        a row that says "there used to be a recording here, and here is what it said".
        """
        with pytest.raises(TypeError):
            VoiceNote.kept(  # type: ignore[call-arg]
                family_id=FAMILY, author_id=PAPA, duration_seconds=4.0, at=NOW
            )

    def test_the_identity_is_the_media_id_rather_than_a_surrogate(self):
        assert a_note().media_id == AUDIO
        assert not hasattr(a_note(), "id")

    def test_attaching_a_transcript_does_not_touch_the_audio_or_the_length(self):
        before = a_note()
        after = before.indexed_by(machine())
        assert after.media_id == before.media_id
        assert after.duration_seconds == before.duration_seconds
        assert after.recorded_at == before.recorded_at

    def test_a_note_with_no_transcript_is_complete_rather_than_pending(self):
        note = a_note()
        assert note.is_indexed is False
        assert note.searchable_text is None


class TestATranscriptSaysWhoMadeIt:
    """PRD 8.7 - AI inference must never silently become family history."""

    def test_a_machine_transcript_is_marked_as_one(self):
        assert machine().source is AttributionSource.AI
        assert machine().is_machine_made is True

    def test_a_machine_transcript_must_name_its_engine(self):
        failed = Transcript.machine("hello", confidence=Confidence(0.7), engine="  ", at=NOW)
        assert failed.unwrap_err().code is ErrorCode.VALIDATION_FAILED

    def test_a_machine_may_not_claim_certainty(self):
        """An engine reporting 1.0 has stopped being able to be wrong."""
        failed = Transcript.machine("hello", confidence=Confidence.CERTAIN, engine="x", at=NOW)
        assert "certainty" in failed.unwrap_err().message

    def test_a_low_confidence_reading_is_marked_uncertain_so_it_renders_as_a_question(self):
        assert machine(confidence=0.3).is_uncertain is True
        assert machine(confidence=0.8).is_uncertain is False

    def test_a_human_transcript_is_certain_and_named_by_hand(self):
        written = Transcript.by_hand("what he actually said", at=NOW).unwrap()
        assert written.source is AttributionSource.HUMAN
        assert written.confidence == Confidence.CERTAIN
        assert written.engine == BY_HAND
        assert written.is_machine_made is False

    @pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
    def test_a_blank_transcript_is_not_a_transcript(self, blank):
        assert Transcript.machine(blank, confidence=Confidence(0.5), engine="x", at=NOW).is_err()
        assert Transcript.by_hand(blank, at=NOW).is_err()

    def test_provenance_is_always_on_the_wire_shape(self):
        assert set(machine().to_dict()) == {"text", "source", "confidence", "engine", "made_at"}


class TestAHumanCorrectionIsPermanent:
    """The same rule `Attributed.reinferred` holds for every other inferred field."""

    def test_a_correction_replaces_a_machine_reading(self):
        corrected = a_note().indexed_by(machine()).corrected_to("an alligator", at=LATER).unwrap()
        assert corrected.transcript is not None
        assert corrected.transcript.text == "an alligator"
        assert corrected.transcript.source is AttributionSource.HUMAN

    def test_a_later_better_model_does_not_undo_it(self):
        corrected = a_note().corrected_to("what he really said", at=LATER).unwrap()
        after = corrected.indexed_by(machine("a much better guess", confidence=0.84))
        assert after.transcript is not None
        assert after.transcript.text == "what he really said"

    def test_a_correction_never_touches_the_audio(self):
        before = a_note()
        after = before.corrected_to("words", at=LATER).unwrap()
        assert after.media_id == before.media_id
        assert after.duration_seconds == before.duration_seconds

    def test_correcting_to_nothing_is_refused_rather_than_erasing_the_index(self):
        assert a_note().indexed_by(machine()).corrected_to("   ", at=LATER).is_err()

    def test_a_correction_is_recorded_on_the_audit_trail_with_its_provenance(self):
        corrected = a_note().corrected_to("words", at=LATER).unwrap()
        indexed = [e for e in corrected.pending_events if isinstance(e, VoiceNoteIndexed)]
        assert indexed == [
            VoiceNoteIndexed(
                aggregate_id="med-1", occurred_at=LATER, engine=BY_HAND, source="HUMAN"
            )
        ]

    def test_the_audit_trail_says_a_reading_happened_without_saying_what_was_heard(self):
        note = a_note().indexed_by(machine("something private about a child"))
        for event in note.pending_events:
            assert "private" not in str(event.payload())


class TestSearchability:
    def test_the_transcript_is_what_a_search_box_may_match_on(self):
        assert a_note().indexed_by(machine()).searchable_text == (
            "he called the elevator an alligator"
        )

    def test_an_unindexed_recording_is_not_hidden_from_the_vault_for_being_unsearchable(self):
        """`None` means "the search box cannot help with this one", not "this is broken"."""
        note = a_note()
        assert note.searchable_text is None
        assert note.media_id == AUDIO
