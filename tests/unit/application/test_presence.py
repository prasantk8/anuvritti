"""TASK-212 - Little Things and Right Now (PRD 17, 18, 48 F8-F9)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.application.presence import (
    CaptureLittleThingCommand,
    CaptureLittleThingUseCase,
    CaptureRightNowCommand,
    CaptureRightNowMilestoneCommand,
    CaptureRightNowMilestoneUseCase,
    CaptureRightNowUseCase,
)
from anuvritti.domain.presence import RIGHT_NOW_PROMPTS
from anuvritti.domain.values import IntentType
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, MemberId, SequentialIdGenerator
from tests.support.fakes import (
    CHILD,
    FAMILY,
    PAPA,
    InMemoryFamilyRepository,
    InMemoryLittleThingRepository,
    InMemoryRightNowRepository,
    InMemorySparkRepository,
    NullUnitOfWork,
    RecordingEventPublisher,
    build_family,
)

NOW = datetime(2026, 8, 25, 7, 30, tzinfo=UTC)


@pytest.fixture
def harness():
    class Harness:
        def __init__(self) -> None:
            self.clock = FrozenClock(NOW)
            self.events = RecordingEventPublisher()
            self.little_things = InMemoryLittleThingRepository()
            self.right_now_repo = InMemoryRightNowRepository()
            self.sparks = InMemorySparkRepository()
            families = InMemoryFamilyRepository(build_family())
            self.little = CaptureLittleThingUseCase(
                families=families,
                little_things=self.little_things,
                events=self.events,
                clock=self.clock,
                ids=SequentialIdGenerator("lt"),
                uow=NullUnitOfWork(),
            )
            self.right_now = CaptureRightNowUseCase(
                families=families,
                right_now=self.right_now_repo,
                events=self.events,
                clock=self.clock,
                ids=SequentialIdGenerator("rn"),
                uow=NullUnitOfWork(),
                sparks=self.sparks,
            )
            self.milestones = CaptureRightNowMilestoneUseCase(
                families=families,
                right_now=self.right_now_repo,
                events=self.events,
                clock=self.clock,
                ids=SequentialIdGenerator("rnm"),
                uow=NullUnitOfWork(),
            )

    return Harness()


class TestLittleThings:
    def test_a_typed_note_is_captured(self, harness):
        thing = harness.little.execute(
            CaptureLittleThingCommand(
                family_id=FAMILY,
                author_id=PAPA,
                subject_child_id=CHILD,
                text="He called the moon a broken sun.",
            )
        ).unwrap()
        assert thing.text is not None

    def test_a_voice_note_alone_is_captured(self, harness):
        """PRD 48 F8 - one-tap voice capture, no structure required."""
        thing = harness.little.execute(
            CaptureLittleThingCommand(family_id=FAMILY, author_id=PAPA, audio_media_id="med-1")
        ).unwrap()
        assert thing.audio_media_id == "med-1"

    def test_no_child_needs_to_be_named(self, harness):
        assert harness.little.execute(
            CaptureLittleThingCommand(family_id=FAMILY, author_id=PAPA, text="something")
        ).is_ok()

    def test_an_empty_capture_is_rejected(self, harness):
        err = harness.little.execute(
            CaptureLittleThingCommand(family_id=FAMILY, author_id=PAPA)
        ).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_it_is_persisted(self, harness):
        harness.little.execute(
            CaptureLittleThingCommand(family_id=FAMILY, author_id=PAPA, text="x")
        ).unwrap()
        assert len(harness.little_things.list_for_family(FAMILY).unwrap()) == 1

    def test_it_publishes_an_event_without_the_words(self, harness):
        harness.little.execute(
            CaptureLittleThingCommand(family_id=FAMILY, author_id=PAPA, text="something private")
        ).unwrap()
        assert "LittleThingCaptured" in harness.events.names()
        assert not any("private" in str(e.payload()) for e in harness.events.events)

    def test_an_unknown_family_is_rejected(self, harness):
        err = harness.little.execute(
            CaptureLittleThingCommand(family_id=FamilyId("nope"), author_id=PAPA, text="x")
        ).unwrap_err()
        assert err.code is ErrorCode.FAMILY_NOT_FOUND

    def test_an_unknown_author_is_rejected(self, harness):
        err = harness.little.execute(
            CaptureLittleThingCommand(family_id=FAMILY, author_id=MemberId("stranger"), text="x")
        ).unwrap_err()
        assert err.code is ErrorCode.MEMBER_NOT_FOUND


class TestRightNow:
    def test_todays_prompt_comes_from_the_curated_library(self, harness):
        assert harness.right_now.todays_prompt() in RIGHT_NOW_PROMPTS

    def test_the_prompt_is_stable_within_a_day(self, harness):
        assert harness.right_now.todays_prompt() == harness.right_now.todays_prompt()

    def test_answering_captures_a_snapshot(self, harness):
        snapshot = harness.right_now.execute(
            CaptureRightNowCommand(
                family_id=FAMILY, child_id=CHILD, answer="Volcanoes. Only volcanoes."
            )
        ).unwrap()
        assert "Volcanoes" in snapshot.answer

    def test_the_system_supplies_the_prompt_so_the_parent_does_not_have_to(self, harness):
        snapshot = harness.right_now.execute(
            CaptureRightNowCommand(family_id=FAMILY, child_id=CHILD, answer="Dinosaurs")
        ).unwrap()
        assert snapshot.prompt in RIGHT_NOW_PROMPTS

    def test_a_custom_prompt_is_accepted(self, harness):
        snapshot = harness.right_now.execute(
            CaptureRightNowCommand(
                family_id=FAMILY, child_id=CHILD, prompt="What made him proud?", answer="His tower"
            )
        ).unwrap()
        assert snapshot.prompt == "What made him proud?"

    def test_an_empty_answer_is_rejected(self, harness):
        err = harness.right_now.execute(
            CaptureRightNowCommand(family_id=FAMILY, child_id=CHILD, answer="   ")
        ).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_an_unknown_child_is_rejected(self, harness):
        err = harness.right_now.execute(
            CaptureRightNowCommand(family_id=FAMILY, child_id=ChildId("ghost"), answer="x")
        ).unwrap_err()
        assert err.code is ErrorCode.CHILD_NOT_FOUND

    def test_it_publishes_an_event_without_the_answer(self, harness):
        harness.right_now.execute(
            CaptureRightNowCommand(family_id=FAMILY, child_id=CHILD, answer="something private")
        ).unwrap()
        assert "RightNowCaptured" in harness.events.names()
        assert not any("private" in str(e.payload()) for e in harness.events.events)

    def test_snapshots_accumulate_over_time(self, harness):
        for answer in ("Trains", "Volcanoes", "Space"):
            harness.clock.advance(days=30)
            harness.right_now.execute(
                CaptureRightNowCommand(family_id=FAMILY, child_id=CHILD, answer=answer)
            ).unwrap()
        assert len(harness.right_now_repo.list_for_family(FAMILY).unwrap()) == 3


class TestAskPapaLater:
    """TASK-811: 'What question did he ask that you could not answer?' -> TELL Spark."""

    def test_unanswerable_question_prompt_creates_tell_spark(self, harness):
        harness.right_now.execute(
            CaptureRightNowCommand(
                family_id=FAMILY,
                child_id=CHILD,
                prompt="What question did he ask that you could not answer?",
                answer="Why is the sky blue and where does the dark go?",
                author_id=PAPA,
            )
        ).unwrap()

        sparks = harness.sparks.list_for_family(FAMILY).unwrap()
        assert len(sparks) == 1
        spark = sparks[0]
        assert spark.intent.value == IntentType.TELL
        assert "Why is the sky blue" in spark.source.title
        assert spark.subject_child_id == CHILD
        assert spark.owner_id == PAPA


class TestMilestoneSnapshots:
    """TASK-817: Multi-field snapshot cadence every few months."""

    def test_captures_multi_field_milestone(self, harness):
        milestone = harness.milestones.execute(
            CaptureRightNowMilestoneCommand(
                family_id=FAMILY,
                child_id=CHILD,
                obsessions="Construction trucks and excavators",
                funny_words="Alligator for elevator",
                favorite_things="Blue blanket",
                interests=("dinosaurs", "space"),
                difficult_questions="How do stars not fall?",
                notes="Loves climbing stairs independently",
            )
        ).unwrap()

        assert milestone.obsessions == "Construction trucks and excavators"
        assert milestone.funny_words == "Alligator for elevator"
        assert milestone.interests == ("dinosaurs", "space")
        assert not milestone.is_due(NOW)  # Just captured, not due
        assert milestone.is_due(NOW.replace(year=2026, month=11))  # Due after months


class TestNoStreaks:
    def test_nothing_in_the_presence_layer_counts_consecutive_days(self):
        """PRD 47 - no streak anxiety. Missing a day must cost nothing.

        Checked against identifiers rather than raw text, so prose explaining *why* the
        product has no streaks does not trip the guard that keeps it that way.
        """
        import ast
        import inspect

        from anuvritti.application import presence

        tree = ast.parse(inspect.getsource(presence))
        identifiers = {
            node.id if isinstance(node, ast.Name) else node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Name | ast.Attribute)
        }
        identifiers |= {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef)
        }
        forbidden = ("streak", "consecutive", "completion_rate", "daily_goal", "target")
        offenders = [
            name for name in identifiers if any(word in name.lower() for word in forbidden)
        ]
        assert not offenders, f"PRD 47 forbids streak mechanics; found {offenders}"
