"""TASK-204 - Little Things and Right Now.

PRD 17: one tap, no structure required. PRD 18: an occasional micro-snapshot of who this
child is *right now*, before it quietly changes into something else.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.domain.events import LittleThingCaptured, RightNowCaptured
from anuvritti.domain.presence import RIGHT_NOW_PROMPTS, LittleThing, RightNowSnapshot
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, LittleThingId, MemberId, RightNowId

T0 = datetime(2026, 8, 25, 7, 30, tzinfo=UTC)


def _little(**kwargs):
    defaults = {
        "little_thing_id": LittleThingId("lt-1"),
        "family_id": FamilyId("fam-1"),
        "author_id": MemberId("mem-papa"),
        "subject_child_id": ChildId("ch-1"),
        "text": "He called the moon a broken sun.",
        "audio_media_id": None,
        "at": T0,
    }
    return LittleThing.capture(**{**defaults, **kwargs})


class TestLittleThing:
    def test_a_text_note_is_enough(self):
        assert _little().unwrap().text is not None

    def test_a_voice_note_alone_is_enough(self):
        """PRD 17 - one-tap voice capture, no structure required."""
        thing = _little(text=None, audio_media_id="med-1").unwrap()
        assert thing.audio_media_id == "med-1"

    def test_something_is_required(self):
        err = _little(text=None, audio_media_id=None).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_blank_text_alone_is_not_enough(self):
        assert _little(text="   ").is_err()

    def test_a_little_thing_need_not_name_a_child(self):
        assert _little(subject_child_id=None).unwrap().subject_child_id is None

    def test_capture_emits_an_event_without_the_words(self):
        thing = _little(text="something tender").unwrap()
        event = thing.pending_events[0]
        assert isinstance(event, LittleThingCaptured)
        assert "tender" not in str(event.payload())

    def test_the_event_records_whether_it_was_spoken(self):
        thing = _little(text=None, audio_media_id="med-1").unwrap()
        event = thing.pending_events[0]
        assert isinstance(event, LittleThingCaptured)
        assert event.has_audio is True

    def test_it_is_frozen(self):
        with pytest.raises(AttributeError):
            _little().unwrap().text = "edited"  # type: ignore[misc]


class TestDictionaryOfUs:
    """TASK-812: 'The Dictionary of Us' - invented words in child's own voice."""

    def test_captures_invented_word_with_meaning(self):
        word = LittleThing.capture_word(
            little_thing_id=LittleThingId("lt-w1"),
            family_id=FamilyId("fam-1"),
            author_id=MemberId("mem-papa"),
            word="Alligator",
            meaning="The elevator in the apartment building",
            at=T0,
            subject_child_id=ChildId("ch-1"),
            audio_media_id="med-voice-1",
        ).unwrap()

        assert word.text == "Alligator"
        assert word.meaning == "The elevator in the apartment building"
        assert word.audio_media_id == "med-voice-1"
        assert word.kind.value == "WORD"

    def test_blank_word_is_rejected(self):
        res = LittleThing.capture_word(
            little_thing_id=LittleThingId("lt-w2"),
            family_id=FamilyId("fam-1"),
            author_id=MemberId("mem-papa"),
            word="   ",
            meaning="Something",
            at=T0,
        )
        assert res.is_err()


def _right_now(**kwargs):
    defaults = {
        "right_now_id": RightNowId("rn-1"),
        "family_id": FamilyId("fam-1"),
        "child_id": ChildId("ch-1"),
        "prompt": "What is he obsessed with this week?",
        "answer": "Volcanoes. Only volcanoes.",
        "at": T0,
    }
    return RightNowSnapshot.capture(**{**defaults, **kwargs})


class TestRightNow:
    def test_a_snapshot_records_the_question_and_the_answer(self):
        snapshot = _right_now().unwrap()
        assert snapshot.prompt.startswith("What is he obsessed")
        assert "Volcanoes" in snapshot.answer

    def test_an_empty_answer_is_rejected(self):
        assert _right_now(answer="  ").unwrap_err().code is ErrorCode.VALIDATION_FAILED

    def test_an_empty_prompt_is_rejected(self):
        assert _right_now(prompt="").is_err()

    def test_capture_emits_an_event_without_the_answer(self):
        snapshot = _right_now(answer="something private").unwrap()
        event = snapshot.pending_events[0]
        assert isinstance(event, RightNowCaptured)
        assert "private" not in str(event.payload())

    def test_a_snapshot_always_names_the_child_it_is_about(self):
        assert _right_now().unwrap().child_id == ChildId("ch-1")


class TestPrompts:
    def test_a_curated_prompt_library_exists(self):
        """PRD 63.6 - content must never overwhelm the relationship, but it must exist."""
        assert len(RIGHT_NOW_PROMPTS) >= 8

    def test_prompts_are_questions(self):
        assert all(p.endswith("?") for p in RIGHT_NOW_PROMPTS)

    def test_no_prompt_asks_the_parent_to_evaluate_the_child(self):
        """PRD 46 - understand and connect, never monitor and optimise."""
        forbidden = ("better than", "behind", "should be able", "compared", "on track", "delayed")
        for prompt in RIGHT_NOW_PROMPTS:
            assert not any(word in prompt.lower() for word in forbidden), prompt

    def test_prompt_for_day_is_stable_for_the_same_day(self):
        assert RightNowSnapshot.prompt_for(T0.date()) == RightNowSnapshot.prompt_for(T0.date())

    def test_prompt_for_day_rotates_over_time(self):
        from datetime import timedelta

        prompts = {RightNowSnapshot.prompt_for(T0.date() + timedelta(days=i)) for i in range(8)}
        assert len(prompts) > 1
