"""TASK-208 - Universal Capture (PRD 11, 12, 48 F1-F3).

    "Share -> Anuvritti"  ... "Saved."   Target: under ten seconds.

The use case must therefore never require a form, never block on AI, and never lose the
one thing that matters most - the reason a person saved it (PRD 12).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.adapters.intent.heuristic import HeuristicIntentEngine
from anuvritti.application.capture import (
    CaptureSparkCommand,
    CaptureSparkUseCase,
    OverrideFieldCommand,
    OverrideFieldUseCase,
    RecordWhyCommand,
    RecordWhyUseCase,
)
from anuvritti.domain.values import (
    AgeRange,
    AttributionSource,
    IntentType,
    SourceKind,
    SourceRef,
    SparkStatus,
    Visibility,
)
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import ChildId, MemberId, SequentialIdGenerator, SparkId
from tests.support.fakes import (
    CHILD,
    FAMILY,
    PAPA,
    InMemoryFamilyRepository,
    InMemorySparkRepository,
    NullUnitOfWork,
    RecordingEventPublisher,
    build_family,
)

NOW = datetime(2026, 8, 25, 7, 30, tzinfo=UTC)
REEL = "https://instagram.com/reel/abc"


@pytest.fixture
def ctx():
    class Ctx:
        def __init__(self) -> None:
            self.clock = FrozenClock(NOW)
            self.families = InMemoryFamilyRepository(build_family())
            self.sparks = InMemorySparkRepository()
            self.events = RecordingEventPublisher()
            self.ids = SequentialIdGenerator("spk")
            self.capture = CaptureSparkUseCase(
                families=self.families,
                sparks=self.sparks,
                intent_engine=HeuristicIntentEngine(),
                events=self.events,
                clock=self.clock,
                ids=self.ids,
                uow=NullUnitOfWork(),
            )
            self.why = RecordWhyUseCase(
                sparks=self.sparks, events=self.events, clock=self.clock, uow=NullUnitOfWork()
            )
            self.override = OverrideFieldUseCase(
                sparks=self.sparks, events=self.events, uow=NullUnitOfWork()
            )

    return Ctx()


def _cmd(**kwargs) -> CaptureSparkCommand:
    defaults = {
        "family_id": FAMILY,
        "owner_id": PAPA,
        "subject_child_id": CHILD,
        "source": SourceRef.from_url(REEL, creator="@sciencedad", title="Balloon rocket"),
        "note": None,
        "visibility": Visibility.PRIVATE,
    }
    return CaptureSparkCommand(**{**defaults, **kwargs})


class TestCapture:
    def test_a_share_becomes_a_saved_spark(self, ctx):
        spark = ctx.capture.execute(_cmd()).unwrap()
        assert ctx.sparks.get(spark.id).is_ok()

    def test_capture_requires_nothing_but_a_source(self, ctx):
        """PRD 11 - no long form, ever."""
        command = CaptureSparkCommand(
            family_id=FAMILY, owner_id=PAPA, source=SourceRef.from_text("teach him to whistle")
        )
        assert ctx.capture.execute(command).is_ok()

    def test_ai_understanding_runs_inline_so_the_spark_is_useful_immediately(self, ctx):
        """PRD 48 F2 - lightweight understanding at capture time."""
        spark = ctx.capture.execute(_cmd()).unwrap()
        assert spark.status is SparkStatus.WAITING
        assert spark.intent.source is AttributionSource.AI

    def test_the_inferred_intent_is_one_of_the_six(self, ctx):
        spark = ctx.capture.execute(_cmd()).unwrap()
        assert spark.intent.value.is_available_in_v0

    def test_the_parents_note_steers_the_inference(self, ctx):
        """PRD 8.1 - Human Before AI."""
        spark = ctx.capture.execute(_cmd(note="I want to teach him this over the summer")).unwrap()
        assert spark.intent.value is IntentType.TEACH

    def test_capture_defaults_to_private(self, ctx):
        spark = ctx.capture.execute(_cmd(visibility=None)).unwrap()
        assert spark.visibility is Visibility.PRIVATE

    def test_capture_records_who_saved_it_and_who_it_is_for(self, ctx):
        spark = ctx.capture.execute(_cmd()).unwrap()
        assert spark.owner_id == PAPA
        assert spark.subject_child_id == CHILD

    def test_a_spark_need_not_be_about_a_child(self, ctx):
        spark = ctx.capture.execute(_cmd(subject_child_id=None)).unwrap()
        assert spark.subject_child_id is None

    def test_ids_are_generated_not_supplied_by_the_caller(self, ctx):
        first = ctx.capture.execute(_cmd()).unwrap()
        second = ctx.capture.execute(_cmd()).unwrap()
        assert first.id != second.id

    def test_capture_publishes_the_audit_events(self, ctx):
        ctx.capture.execute(_cmd()).unwrap()
        assert ctx.events.names() == ["SparkCaptured", "SparkEnriched"]

    def test_the_stored_spark_carries_no_unpublished_events(self, ctx):
        spark = ctx.capture.execute(_cmd()).unwrap()
        assert ctx.sparks.get(spark.id).unwrap().pending_events == ()

    @pytest.mark.parametrize(
        "source",
        [
            SourceRef.from_url("https://youtube.com/watch?v=1", title="Volcano"),
            SourceRef.from_text("he said the moon was a broken sun"),
            SourceRef.from_media(SourceKind.SCREENSHOT, media_id="med-1"),
            SourceRef.from_media(SourceKind.PHOTO, media_id="med-2"),
            SourceRef.from_media(SourceKind.VOICE, media_id="med-3"),
        ],
        ids=["url", "text", "screenshot", "photo", "voice"],
    )
    def test_every_v0_capture_channel_is_accepted(self, ctx, source):
        """PRD 48 F1 - URL, screenshot, photo, voice, text."""
        assert ctx.capture.execute(_cmd(source=source)).is_ok()


class TestCapturePermissions:
    def test_an_unknown_family_is_rejected(self, ctx):
        from anuvritti.shared.identity import FamilyId

        err = ctx.capture.execute(_cmd(family_id=FamilyId("nope"))).unwrap_err()
        assert err.code is ErrorCode.FAMILY_NOT_FOUND

    def test_an_unknown_member_cannot_capture(self, ctx):
        err = ctx.capture.execute(_cmd(owner_id=MemberId("stranger"))).unwrap_err()
        assert err.code is ErrorCode.MEMBER_NOT_FOUND

    def test_capturing_for_an_unknown_child_is_rejected(self, ctx):
        err = ctx.capture.execute(_cmd(subject_child_id=ChildId("ghost"))).unwrap_err()
        assert err.code is ErrorCode.CHILD_NOT_FOUND

    def test_nothing_is_written_when_permission_is_denied(self, ctx):
        ctx.capture.execute(_cmd(owner_id=MemberId("stranger")))
        assert ctx.sparks.list_for_family(FAMILY).unwrap() == []
        assert ctx.events.events == []


class TestRecordWhy:
    def test_a_written_why_is_attached(self, ctx):
        """PRD 12 - "Toy -> Age 3" dies; "I never had one growing up" survives decades."""
        spark = ctx.capture.execute(_cmd()).unwrap()
        updated = ctx.why.execute(
            RecordWhyCommand(spark_id=spark.id, text="I never had one growing up")
        ).unwrap()
        assert updated.why.text == "I never had one growing up"

    def test_a_voice_why_is_attached(self, ctx):
        spark = ctx.capture.execute(_cmd()).unwrap()
        updated = ctx.why.execute(
            RecordWhyCommand(spark_id=spark.id, voice_media_id="med-9")
        ).unwrap()
        assert updated.why.voice_media_id == "med-9"

    def test_skipping_is_always_allowed(self, ctx):
        """PRD 48 F3 - "Skip always allowed." A Spark without a why is complete."""
        spark = ctx.capture.execute(_cmd()).unwrap()
        assert spark.why is None
        assert ctx.sparks.get(spark.id).is_ok()

    def test_an_empty_why_is_rejected_rather_than_stored_blank(self, ctx):
        spark = ctx.capture.execute(_cmd()).unwrap()
        err = ctx.why.execute(RecordWhyCommand(spark_id=spark.id)).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_recording_a_why_for_an_unknown_spark_fails(self, ctx):
        err = ctx.why.execute(RecordWhyCommand(spark_id=SparkId("nope"), text="x")).unwrap_err()
        assert err.code is ErrorCode.SPARK_NOT_FOUND

    def test_the_why_is_persisted(self, ctx):
        spark = ctx.capture.execute(_cmd()).unwrap()
        ctx.why.execute(RecordWhyCommand(spark_id=spark.id, text="because")).unwrap()
        assert ctx.sparks.get(spark.id).unwrap().why is not None

    def test_recording_a_why_publishes_an_event_without_the_words(self, ctx):
        spark = ctx.capture.execute(_cmd()).unwrap()
        ctx.why.execute(RecordWhyCommand(spark_id=spark.id, text="something private")).unwrap()
        assert "SparkWhyRecorded" in ctx.events.names()
        assert not any("private" in str(e.payload()) for e in ctx.events.events)


class TestOverride:
    def test_a_parent_can_correct_the_inferred_intent(self, ctx):
        spark = ctx.capture.execute(_cmd()).unwrap()
        updated = ctx.override.execute(
            OverrideFieldCommand(spark_id=spark.id, field="intent", value=IntentType.BUY)
        ).unwrap()
        assert updated.intent.value is IntentType.BUY
        assert updated.intent.human_override is True

    def test_a_parent_can_correct_the_age_range(self, ctx):
        spark = ctx.capture.execute(_cmd()).unwrap()
        updated = ctx.override.execute(
            OverrideFieldCommand(spark_id=spark.id, field="age_range", value=AgeRange(2, 3))
        ).unwrap()
        assert updated.age_range.value == AgeRange(2, 3)

    def test_a_parent_can_correct_the_category(self, ctx):
        spark = ctx.capture.execute(_cmd()).unwrap()
        updated = ctx.override.execute(
            OverrideFieldCommand(spark_id=spark.id, field="category", value="toy")
        ).unwrap()
        assert updated.category.value == "toy"

    def test_an_unknown_field_is_rejected(self, ctx):
        spark = ctx.capture.execute(_cmd()).unwrap()
        err = ctx.override.execute(
            OverrideFieldCommand(spark_id=spark.id, field="mood", value="happy")
        ).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_a_wrongly_typed_value_is_rejected(self, ctx):
        spark = ctx.capture.execute(_cmd()).unwrap()
        err = ctx.override.execute(
            OverrideFieldCommand(spark_id=spark.id, field="intent", value="not-an-intent")
        ).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_the_override_survives_a_later_re_capture_of_the_same_content(self, ctx):
        """PRD 13 - human override always wins, permanently."""
        spark = ctx.capture.execute(_cmd()).unwrap()
        ctx.override.execute(
            OverrideFieldCommand(spark_id=spark.id, field="intent", value=IntentType.TEACH)
        ).unwrap()
        stored = ctx.sparks.get(spark.id).unwrap()
        reinferred = stored.apply_inference(HeuristicIntentEngine().infer(stored.source))
        assert reinferred.intent.value is IntentType.TEACH
