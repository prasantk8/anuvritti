"""TASK-811 - Ask Papa, later unit tests (PRD 8.1, 17, 33)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from anuvritti.application.returns import (
    AnswerDeferredQuestionCommand,
    DeferredQuestionsUseCase,
)
from anuvritti.domain.family import ChildProfile, Family, Member
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import IntentType, MemberRole, SourceRef
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    MemberId,
    SequentialIdGenerator,
    SparkId,
)
from tests.support.fakes import (
    InMemoryFamilyRepository,
    InMemoryMomentRepository,
    InMemorySparkRepository,
    NullUnitOfWork,
    RecordingEventPublisher,
)

PAPA = MemberId("mem-papa")
CHILD = ChildId("ch-1")
FAMILY = FamilyId("fam-1")
T_PAST = datetime(2022, 6, 1, 10, 0, tzinfo=UTC)
T_NOW = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)


@pytest.fixture
def harness():
    class Harness:
        def __init__(self) -> None:
            self.clock = FrozenClock(T_NOW)
            self.events = RecordingEventPublisher()
            self.sparks = InMemorySparkRepository()
            self.moments = InMemoryMomentRepository()
            family = Family(
                id=FAMILY,
                name="Our family",
                members=(Member(PAPA, "Papa", MemberRole.PARENT),),
                children=(ChildProfile(CHILD, MemberId("mem-son"), "Aarav", date(2018, 1, 1)),),
                created_at=datetime(2020, 1, 1, tzinfo=UTC),
            )
            self.families = InMemoryFamilyRepository(family)
            self.use_case = DeferredQuestionsUseCase(
                families=self.families,
                sparks=self.sparks,
                moments=self.moments,
                events=self.events,
                clock=self.clock,
                ids=SequentialIdGenerator("ret"),
                uow=NullUnitOfWork(),
            )

    return Harness()


class TestDeferredAnswers:
    def test_surfaces_question_when_child_is_older(self, harness):
        spark = (
            Spark.capture(
                spark_id=SparkId("spk-q1"),
                family_id=FAMILY,
                owner_id=PAPA,
                subject_child_id=CHILD,
                source=SourceRef.from_text(
                    "Why is the moon following us?", title="Question from Aarav"
                ),
                at=T_PAST,
            )
            .override_intent(IntentType.TELL)
            .unwrap()
        )
        harness.sparks.save(spark).unwrap()

        surfaced = harness.use_case.surface_for_child(FAMILY, CHILD).unwrap()
        assert len(surfaced) == 1
        assert surfaced[0].prompt_text == "Aarav asked this when Aarav was 4."

    def test_recording_answer_creates_moment_and_experiences_spark(self, harness):
        spark = (
            Spark.capture(
                spark_id=SparkId("spk-q1"),
                family_id=FAMILY,
                owner_id=PAPA,
                subject_child_id=CHILD,
                source=SourceRef.from_text(
                    "Why is the moon following us?", title="Why the moon follows"
                ),
                at=T_PAST,
            )
            .override_intent(IntentType.TELL)
            .unwrap()
        )
        harness.sparks.save(spark).unwrap()

        moment = harness.use_case.answer_question(
            AnswerDeferredQuestionCommand(
                family_id=FAMILY,
                spark_id=SparkId("spk-q1"),
                author_id=PAPA,
                audio_media_id="med-answer-1",
                note="I explained relative motion and parallax with trees.",
            )
        ).unwrap()

        assert "What Papa found out" in (moment.reflection or "")
        assert moment.audio_media_id == "med-answer-1"
        assert "DeferredQuestionAnswered" in harness.events.names()

        # Spark is now experienced, not surfaced again
        surfaced_after = harness.use_case.surface_for_child(FAMILY, CHILD).unwrap()
        assert len(surfaced_after) == 0
