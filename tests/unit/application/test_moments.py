"""TASK-211 - Mark As Done (PRD 15, 48 F7).

    "Did this happen?"  ->  one photo, five seconds of audio, one sentence, or nothing.
    "No journaling burden."

This is the use case the product is judged by (PRD 53), so it must be the easiest one to
complete successfully.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from anuvritti.adapters.intent.heuristic import HeuristicIntentEngine
from anuvritti.application.capture import CaptureSparkCommand, CaptureSparkUseCase
from anuvritti.application.moments import MarkAsDoneCommand, MarkAsDoneUseCase
from anuvritti.domain.events import MomentCreated
from anuvritti.domain.values import SourceRef, SparkStatus
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import SequentialIdGenerator, SparkId
from tests.support.fakes import (
    CHILD,
    FAMILY,
    PAPA,
    InMemoryFamilyRepository,
    InMemoryMomentRepository,
    InMemorySparkRepository,
    NullUnitOfWork,
    RecordingEventPublisher,
    build_family,
)

CAPTURED_AT = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
DONE_AT = CAPTURED_AT + timedelta(days=243)


@pytest.fixture
def harness():
    class Harness:
        def __init__(self) -> None:
            self.clock = FrozenClock(CAPTURED_AT)
            self.sparks = InMemorySparkRepository()
            self.moments = InMemoryMomentRepository()
            self.events = RecordingEventPublisher()
            self._capture = CaptureSparkUseCase(
                families=InMemoryFamilyRepository(build_family()),
                sparks=self.sparks,
                intent_engine=HeuristicIntentEngine(),
                events=self.events,
                clock=self.clock,
                ids=SequentialIdGenerator("spk"),
                uow=NullUnitOfWork(),
            )
            self.done_clock = FrozenClock(DONE_AT)
            self.mark_done = MarkAsDoneUseCase(
                sparks=self.sparks,
                moments=self.moments,
                events=self.events,
                clock=self.done_clock,
                ids=SequentialIdGenerator("mom"),
                uow=NullUnitOfWork(),
            )

        def capture(self):
            return self._capture.execute(
                CaptureSparkCommand(
                    family_id=FAMILY,
                    owner_id=PAPA,
                    subject_child_id=CHILD,
                    source=SourceRef.from_url(
                        "https://youtube.com/watch?v=1", title="Balloon rocket experiment"
                    ),
                )
            ).unwrap()

    return Harness()


class TestMarkAsDone:
    def test_nothing_attached_is_a_valid_answer(self, harness):
        """PRD 15 - "Capture can be ... nothing." No journaling burden."""
        spark = harness.capture()
        moment = harness.mark_done.execute(
            MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA)
        ).unwrap()
        assert moment.has_evidence is False

    def test_one_sentence_is_enough(self, harness):
        spark = harness.capture()
        moment = harness.mark_done.execute(
            MarkAsDoneCommand(
                spark_id=spark.id, created_by=PAPA, reflection="He laughed until he fell over."
            )
        ).unwrap()
        assert moment.reflection is not None

    def test_one_photo_is_enough(self, harness):
        spark = harness.capture()
        moment = harness.mark_done.execute(
            MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA, photo_media_id="med-1")
        ).unwrap()
        assert moment.photo_media_id == "med-1"

    def test_five_seconds_of_audio_is_enough(self, harness):
        spark = harness.capture()
        moment = harness.mark_done.execute(
            MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA, audio_media_id="med-2")
        ).unwrap()
        assert moment.audio_media_id == "med-2"

    def test_the_spark_becomes_experienced(self, harness):
        spark = harness.capture()
        harness.mark_done.execute(MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA)).unwrap()
        assert harness.sparks.get(spark.id).unwrap().status is SparkStatus.EXPERIENCED

    def test_the_moment_is_persisted_and_linked_to_its_spark(self, harness):
        spark = harness.capture()
        moment = harness.mark_done.execute(
            MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA)
        ).unwrap()
        assert harness.moments.find_by_spark(spark.id).unwrap().id == moment.id

    def test_it_can_be_backdated_to_when_it_actually_happened(self, harness):
        spark = harness.capture()
        moment = harness.mark_done.execute(
            MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA, happened_on=date(2026, 8, 1))
        ).unwrap()
        assert moment.happened_on == date(2026, 8, 1)

    def test_something_done_without_ever_being_suggested_still_counts(self, harness):
        """Real life does not wait for a notification."""
        spark = harness.capture()
        assert harness.mark_done.execute(
            MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA)
        ).is_ok()


class TestTheConversionMetric:
    def test_a_moment_created_event_is_published(self, harness):
        spark = harness.capture()
        harness.mark_done.execute(MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA)).unwrap()
        assert "MomentCreated" in harness.events.names()

    def test_the_event_records_how_long_the_intention_waited(self, harness):
        """PRD 53 - this number is the product's primary north star."""
        spark = harness.capture()
        harness.mark_done.execute(MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA)).unwrap()
        event = next(e for e in harness.events.events if isinstance(e, MomentCreated))
        assert event.days_from_capture == 243

    def test_the_event_records_what_was_kept_but_not_its_content(self, harness):
        spark = harness.capture()
        harness.mark_done.execute(
            MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA, reflection="something private")
        ).unwrap()
        event = next(e for e in harness.events.events if isinstance(e, MomentCreated))
        assert event.has_reflection is True
        assert "private" not in str(event.payload())


class TestFailures:
    def test_an_unknown_spark_fails(self, harness):
        err = harness.mark_done.execute(
            MarkAsDoneCommand(spark_id=SparkId("nope"), created_by=PAPA)
        ).unwrap_err()
        assert err.code is ErrorCode.SPARK_NOT_FOUND

    def test_the_same_spark_cannot_become_two_moments(self, harness):
        spark = harness.capture()
        harness.mark_done.execute(MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA)).unwrap()
        err = harness.mark_done.execute(
            MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA)
        ).unwrap_err()
        assert err.code is ErrorCode.CONFLICT

    def test_an_archived_spark_cannot_be_marked_done(self, harness):
        spark = harness.capture()
        harness.sparks.save(spark.archive().unwrap())
        err = harness.mark_done.execute(
            MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA)
        ).unwrap_err()
        assert err.code is ErrorCode.SPARK_ARCHIVED

    def test_a_future_date_is_rejected(self, harness):
        spark = harness.capture()
        err = harness.mark_done.execute(
            MarkAsDoneCommand(
                spark_id=spark.id, created_by=PAPA, happened_on=DONE_AT.date() + timedelta(days=5)
            )
        ).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_a_failed_mark_done_leaves_no_moment_behind(self, harness):
        spark = harness.capture()
        harness.mark_done.execute(
            MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA, happened_on=date(2020, 1, 1))
        )
        assert harness.moments.list_for_family(FAMILY).unwrap() == []
