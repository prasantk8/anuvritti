"""TASK-810 - Annual Birthday Interview unit tests (PRD 34, 52, 24)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from anuvritti.domain.interview import (
    DEFAULT_INTERVIEW_QUESTIONS,
    AnnualInterview,
    InterviewAnswer,
)
from anuvritti.shared.identity import ChildId, FamilyId

FAMILY = FamilyId("fam-1")
CHILD = ChildId("ch-1")
NOW = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)


class TestAnnualInterview:
    def test_records_annual_birthday_interview_in_two_voices(self):
        answers = (
            InterviewAnswer(
                question="What is Papa terrible at?",
                child_audio_media_id="med-child-roar",
                child_answer_text="Singing bedtime songs!",
                parent_audio_media_id="med-papa-admit",
                parent_answer_text="Finding lost socks.",
            ),
            InterviewAnswer(
                question="What is your favourite thing to do together?",
                child_audio_media_id="med-child-fav",
                child_answer_text="Building blanket forts.",
            ),
        )

        res = AnnualInterview.record(
            interview_id="int-age-4",
            family_id=FAMILY,
            child_id=CHILD,
            age_years=4,
            recorded_on=date(2026, 8, 25),
            answers=answers,
            at=NOW,
        )

        assert res.is_ok()
        interview = res.unwrap()
        assert interview.age_years == 4
        assert len(interview.answers) == 2
        assert len(interview.pending_events) == 1
        assert interview.pending_events[0].name == "AnnualInterviewRecorded"

    def test_default_curated_questions_are_positive_and_gentle(self):
        assert len(DEFAULT_INTERVIEW_QUESTIONS) >= 4
        assert "What is Papa terrible at?" in DEFAULT_INTERVIEW_QUESTIONS

    def test_empty_interview_is_rejected(self):
        res = AnnualInterview.record(
            interview_id="int-empty",
            family_id=FAMILY,
            child_id=CHILD,
            age_years=5,
            recorded_on=date(2026, 8, 25),
            answers=(),
            at=NOW,
        )
        assert res.is_err()
