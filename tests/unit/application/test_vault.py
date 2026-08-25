"""TASK-209 - the Safe Vault (PRD 48 F5).

The PRD names the queries this has to answer, in the words a father would use:

    toys I saved / things for age 3 / funny things / things about space /
    things to do outside / things I wanted to teach him

"No complex folder management." So there are no folders - only what the thing is, who it
is for, and what you meant to do with it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from anuvritti.adapters.intent.heuristic import HeuristicIntentEngine
from anuvritti.application.capture import CaptureSparkCommand, CaptureSparkUseCase
from anuvritti.application.vault import SearchVaultQuery, SearchVaultUseCase
from anuvritti.domain.values import IntentType, SourceRef, Visibility
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

NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)

#: A small, realistic archive - the kind one father accumulates in a few months.
ARCHIVE = [
    ("https://amazon.in/dp/1", "Wooden balance bike for toddlers", "he is nearly ready"),
    ("https://amazon.in/dp/2", "Magnetic building blocks toy set", None),
    ("https://youtube.com/watch?v=1", "Baking soda volcano experiment", "do this outdoors"),
    ("https://youtube.com/watch?v=2", "Funny cat compilation", "this made him laugh"),
    ("https://nasa.gov/kids", "Space rockets explained for ages 5-8", None),
    ("https://blog.com/teach", "How to teach a child about honesty", "I want to teach him this"),
    ("https://blog.com/outdoor", "Outdoor scavenger hunt activity", "for a weekend"),
    ("https://goodreads.com/book/1", "Bedtime story book about elephants", None),
]


@pytest.fixture
def vault():
    class Vault:
        def __init__(self) -> None:
            clock = FrozenClock(NOW)
            self.sparks = InMemorySparkRepository()
            capture = CaptureSparkUseCase(
                families=InMemoryFamilyRepository(build_family()),
                sparks=self.sparks,
                intent_engine=HeuristicIntentEngine(),
                events=RecordingEventPublisher(),
                clock=clock,
                ids=SequentialIdGenerator("spk"),
                uow=NullUnitOfWork(),
            )
            for index, (url, title, note) in enumerate(ARCHIVE):
                clock.advance(days=index)
                capture.execute(
                    CaptureSparkCommand(
                        family_id=FAMILY,
                        owner_id=PAPA,
                        subject_child_id=CHILD,
                        source=SourceRef.from_url(url, title=title),
                        note=note,
                        visibility=Visibility.PRIVATE,
                    )
                ).unwrap()
            self.search = SearchVaultUseCase(
                families=InMemoryFamilyRepository(build_family()),
                sparks=self.sparks,
                clock=FrozenClock(NOW),
            )

        def run(self, **kwargs):
            return self.search.execute(
                SearchVaultQuery(family_id=FAMILY, actor_id=PAPA, **kwargs)
            ).unwrap()

    return Vault()


class TestPrdQueries:
    """Each of these is a query the PRD explicitly promises."""

    def test_toys_i_saved(self, vault):
        titles = [s.title for s in vault.run(text="toy")]
        assert any("blocks" in t.lower() for t in titles)

    def test_things_for_age_3(self, vault):
        results = vault.run(age_years=3)
        assert results
        assert all(s.is_age_appropriate_for(3) for s in results)

    def test_things_about_space(self, vault):
        assert any("Space" in s.title for s in vault.run(text="space"))

    def test_things_to_do_outside(self, vault):
        titles = [s.title.lower() for s in vault.run(text="outdoor")]
        assert any("scavenger" in t for t in titles)

    def test_things_i_wanted_to_teach_him(self, vault):
        results = vault.run(intent=IntentType.TEACH)
        assert results
        assert all(s.intent.value is IntentType.TEACH for s in results)

    def test_things_to_watch(self, vault):
        assert all(s.intent.value is IntentType.WATCH for s in vault.run(intent=IntentType.WATCH))

    def test_everything_is_findable_with_no_query_at_all(self, vault):
        """PRD 48 F5 - "Everything captured should remain searchable"."""
        assert len(vault.run()) == len(ARCHIVE)


class TestSearchBehaviour:
    def test_search_is_case_insensitive(self, vault):
        assert vault.run(text="SPACE") == vault.run(text="space")

    def test_search_matches_the_note_the_parent_typed(self, vault):
        """The parent's own words are part of the index (PRD 12)."""
        assert any("laugh" in (s.note or "") for s in vault.run(text="laugh"))

    def test_search_matches_inferred_tags(self, vault):
        assert vault.run(text="science-activity")

    def test_an_unmatched_query_returns_nothing_rather_than_guessing(self, vault):
        assert vault.run(text="submarine") == []

    def test_results_are_newest_first(self, vault):
        results = vault.run()
        assert results == sorted(results, key=lambda s: s.created_at, reverse=True)

    def test_filters_combine(self, vault):
        results = vault.run(intent=IntentType.BUY, child_id=CHILD)
        assert all(s.intent.value is IntentType.BUY for s in results)

    def test_the_limit_is_honoured(self, vault):
        assert len(vault.run(limit=2)) == 2

    def test_the_limit_is_capped_to_protect_the_process(self, vault):
        assert len(vault.run(limit=10_000)) <= SearchVaultUseCase.MAX_LIMIT

    def test_a_zero_or_negative_limit_is_rejected(self, vault):
        result = vault.search.execute(SearchVaultQuery(family_id=FAMILY, actor_id=PAPA, limit=0))
        assert result.unwrap_err().code is ErrorCode.VALIDATION_FAILED

    def test_searching_an_unknown_family_fails(self, vault):
        result = vault.search.execute(SearchVaultQuery(family_id=FamilyId("nope"), actor_id=PAPA))
        assert result.unwrap_err().code is ErrorCode.FAMILY_NOT_FOUND

    def test_searching_as_an_unknown_member_fails(self, vault):
        result = vault.search.execute(
            SearchVaultQuery(family_id=FAMILY, actor_id=MemberId("stranger"))
        )
        assert result.unwrap_err().code is ErrorCode.MEMBER_NOT_FOUND


class TestVisibility:
    def test_a_child_cannot_see_a_parents_private_sparks(self, vault):
        """PRD 45 - a parent's private note about a child is not the child's feed."""
        from anuvritti.domain.family import Member
        from anuvritti.domain.values import MemberRole

        family = build_family().with_member(Member(MemberId("mem-kid"), "Aarav", MemberRole.CHILD))
        search = SearchVaultUseCase(
            families=InMemoryFamilyRepository(family),
            sparks=vault.sparks,
            clock=FrozenClock(NOW),
        )
        visible = search.execute(
            SearchVaultQuery(family_id=FAMILY, actor_id=MemberId("mem-kid"))
        ).unwrap()
        assert visible == []

    def test_a_parent_sees_their_own_private_sparks(self, vault):
        assert vault.run()


class TestAgeAwareness:
    def test_age_filtering_uses_the_childs_real_age_when_asked_for_mine(self, vault):
        """ "things for him right now" resolves the child's age from the profile."""
        results = vault.run(child_id=CHILD, use_child_age=True)
        assert all(s.is_age_appropriate_for(5) for s in results)

    def test_use_child_age_without_a_child_is_ignored_rather_than_erroring(self, vault):
        assert vault.run(use_child_age=True) is not None

    def test_a_spark_with_no_age_range_is_never_filtered_out_by_age(self, vault):
        results = vault.run(age_years=1)
        assert any(s.age_range is None for s in results)


class TestFreshness:
    def test_a_spark_captured_today_is_immediately_searchable(self, vault):
        clock = FrozenClock(NOW + timedelta(days=1))
        capture = CaptureSparkUseCase(
            families=InMemoryFamilyRepository(build_family()),
            sparks=vault.sparks,
            intent_engine=HeuristicIntentEngine(),
            events=RecordingEventPublisher(),
            clock=clock,
            ids=SequentialIdGenerator("late"),
            uow=NullUnitOfWork(),
        )
        capture.execute(
            CaptureSparkCommand(
                family_id=FAMILY,
                owner_id=PAPA,
                source=SourceRef.from_text("submarine documentary"),
            )
        ).unwrap()
        assert vault.run(text="submarine")
