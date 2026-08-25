"""TASK-210 - Worth Bringing Back (PRD 14, 48 F6).

The PRD's own example is the acceptance criterion:

    You saved this 8 months ago.
    You thought he might enjoy it once he was a little older.
    He may be ready now.
    [Maybe later] [Let's do it] [Not relevant anymore]

    "No guilt. No fake urgency."
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from anuvritti.adapters.intent.heuristic import HeuristicIntentEngine
from anuvritti.application.capture import CaptureSparkCommand, CaptureSparkUseCase
from anuvritti.application.returning import (
    GetWorthBringingBackUseCase,
    RespondToSuggestionCommand,
    RespondToSuggestionUseCase,
    SuggestionResponse,
    WorthBringingBackQuery,
)
from anuvritti.domain.return_engine import ReturnEngine
from anuvritti.domain.values import SourceRef, SparkStatus
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import FamilyId, MemberId, SequentialIdGenerator
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

CAPTURED_AT = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
EIGHT_MONTHS_LATER = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)  # a Saturday


class Harness:
    def __init__(self, *, now: datetime = EIGHT_MONTHS_LATER, threshold: float = 0.0) -> None:
        self.clock = FrozenClock(CAPTURED_AT)
        self.sparks = InMemorySparkRepository()
        self.events = RecordingEventPublisher()
        self.families = InMemoryFamilyRepository(build_family())
        self._capture = CaptureSparkUseCase(
            families=self.families,
            sparks=self.sparks,
            intent_engine=HeuristicIntentEngine(),
            events=self.events,
            clock=self.clock,
            ids=SequentialIdGenerator("spk"),
            uow=NullUnitOfWork(),
        )
        self.now_clock = FrozenClock(now)
        self.get = GetWorthBringingBackUseCase(
            families=self.families,
            sparks=self.sparks,
            engine=ReturnEngine(),
            events=self.events,
            clock=self.now_clock,
            uow=NullUnitOfWork(),
            threshold=threshold,
        )
        self.respond = RespondToSuggestionUseCase(
            sparks=self.sparks,
            events=self.events,
            clock=self.now_clock,
            uow=NullUnitOfWork(),
            snooze_cooldown_days=30,
        )

    def capture(self, title: str = "Balloon rocket experiment for ages 5-8", note=None):
        return self._capture.execute(
            CaptureSparkCommand(
                family_id=FAMILY,
                owner_id=PAPA,
                subject_child_id=CHILD,
                source=SourceRef.from_url("https://youtube.com/watch?v=1", title=title),
                note=note,
            )
        ).unwrap()

    def ask(self, **kwargs):
        return self.get.execute(
            WorthBringingBackQuery(family_id=FAMILY, actor_id=PAPA, **kwargs)
        ).unwrap()


@pytest.fixture
def harness():
    return Harness()


class TestTheGoldenSuggestion:
    def test_a_spark_saved_months_ago_comes_back(self, harness):
        harness.capture()
        assert len(harness.ask()) == 1

    def test_the_suggestion_says_how_long_it_has_been(self, harness):
        harness.capture()
        assert "8 months ago" in harness.ask()[0].reason

    def test_the_suggestion_repeats_the_parents_own_why(self, harness):
        """PRD 12/14 - the reason it mattered is what makes it worth returning."""
        spark = harness.capture()
        from anuvritti.application.capture import RecordWhyCommand, RecordWhyUseCase

        RecordWhyUseCase(
            sparks=harness.sparks,
            events=harness.events,
            clock=harness.clock,
            uow=NullUnitOfWork(),
        ).execute(RecordWhyCommand(spark_id=spark.id, text="I never had one growing up")).unwrap()
        assert "I never had one growing up" in harness.ask()[0].reason

    def test_the_suggestion_offers_exactly_the_three_prd_actions(self, harness):
        harness.capture()
        assert harness.ask()[0].actions == ("maybe_later", "lets_do_it", "not_relevant_anymore")

    def test_a_spark_saved_today_is_not_pushed_back_immediately(self):
        harness = Harness(now=CAPTURED_AT + timedelta(hours=2), threshold=0.45)
        harness.capture()
        assert harness.ask() == []


class TestQuietByDefault:
    def test_an_empty_archive_returns_nothing_and_says_nothing(self, harness):
        assert harness.ask() == []

    def test_the_daily_cap_is_enforced(self):
        """PRD 53 anti-metric - notification volume is minimised, not maximised."""
        harness = Harness()
        for i in range(10):
            harness.capture(title=f"Experiment {i} for ages 5-8")
        assert len(harness.ask()) <= 3

    def test_surfacing_marks_the_spark_so_it_decays(self, harness):
        harness.capture()
        first = harness.ask()
        assert first
        stored = harness.sparks.get(first[0].spark.id).unwrap()
        assert stored.status is SparkStatus.SUGGESTED
        assert stored.suggested_count == 1

    def test_surfacing_publishes_an_auditable_event(self, harness):
        harness.capture()
        harness.ask()
        assert "SparkSuggested" in harness.events.names()

    def test_a_child_filter_narrows_the_result(self, harness):
        harness.capture()
        assert harness.ask(child_id=CHILD)
        from anuvritti.shared.identity import ChildId

        assert harness.ask(child_id=ChildId("other")) == []


class TestResponses:
    def test_lets_do_it_plans_the_spark(self, harness):
        spark = harness.capture()
        harness.ask()
        updated = harness.respond.execute(
            RespondToSuggestionCommand(spark.id, SuggestionResponse.LETS_DO_IT)
        ).unwrap()
        assert updated.status is SparkStatus.PLANNED

    def test_maybe_later_buys_real_quiet(self, harness):
        """PRD 8.5 - "maybe later" must mean later, not tomorrow."""
        spark = harness.capture()
        harness.ask()
        harness.respond.execute(
            RespondToSuggestionCommand(spark.id, SuggestionResponse.MAYBE_LATER)
        ).unwrap()
        assert harness.ask() == []

    def test_maybe_later_expires_after_the_cooldown(self, harness):
        spark = harness.capture()
        harness.ask()
        harness.respond.execute(
            RespondToSuggestionCommand(spark.id, SuggestionResponse.MAYBE_LATER)
        ).unwrap()
        harness.now_clock.advance(days=31)
        assert len(harness.ask()) == 1

    def test_not_relevant_anymore_is_permanent(self, harness):
        """The system must take no for an answer, forever."""
        spark = harness.capture()
        harness.ask()
        harness.respond.execute(
            RespondToSuggestionCommand(spark.id, SuggestionResponse.NOT_RELEVANT_ANYMORE)
        ).unwrap()
        harness.now_clock.advance(days=3650)
        assert harness.ask() == []

    def test_responding_to_an_archived_spark_fails_clearly(self, harness):
        spark = harness.capture()
        harness.ask()
        harness.respond.execute(
            RespondToSuggestionCommand(spark.id, SuggestionResponse.NOT_RELEVANT_ANYMORE)
        ).unwrap()
        err = harness.respond.execute(
            RespondToSuggestionCommand(spark.id, SuggestionResponse.LETS_DO_IT)
        ).unwrap_err()
        assert err.code is ErrorCode.SPARK_ARCHIVED

    def test_responding_to_an_unknown_spark_fails(self, harness):
        from anuvritti.shared.identity import SparkId

        err = harness.respond.execute(
            RespondToSuggestionCommand(SparkId("nope"), SuggestionResponse.LETS_DO_IT)
        ).unwrap_err()
        assert err.code is ErrorCode.SPARK_NOT_FOUND

    def test_each_response_publishes_its_event(self, harness):
        spark = harness.capture()
        harness.ask()
        harness.respond.execute(
            RespondToSuggestionCommand(spark.id, SuggestionResponse.MAYBE_LATER)
        ).unwrap()
        assert "SparkSnoozed" in harness.events.names()


class TestPermissions:
    def test_an_unknown_family_fails(self, harness):
        result = harness.get.execute(
            WorthBringingBackQuery(family_id=FamilyId("nope"), actor_id=PAPA)
        )
        assert result.unwrap_err().code is ErrorCode.FAMILY_NOT_FOUND

    def test_an_unknown_member_fails(self, harness):
        result = harness.get.execute(
            WorthBringingBackQuery(family_id=FAMILY, actor_id=MemberId("stranger"))
        )
        assert result.unwrap_err().code is ErrorCode.MEMBER_NOT_FOUND

    def test_a_child_is_not_shown_a_parents_private_sparks(self, harness):
        from anuvritti.domain.family import Member
        from anuvritti.domain.values import MemberRole

        harness.capture()
        harness.families.save(
            build_family().with_member(Member(MemberId("mem-kid"), "Aarav", MemberRole.CHILD))
        )
        result = harness.get.execute(
            WorthBringingBackQuery(family_id=FAMILY, actor_id=MemberId("mem-kid"))
        )
        assert result.unwrap() == []
