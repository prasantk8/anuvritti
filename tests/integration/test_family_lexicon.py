"""TASK-801 - a correction that actually changes the next capture (PRD 44, 13, 8.1).

The domain tests prove the lexicon is honest. These prove it is connected: a parent taps
the intent chip twice, a week later they share something similar, and the product has
learned their word — through the real SQLite file, the real use cases and the real engine.

The last class is the one that matters most. It builds two families in one database and
checks that neither can hear the other, because a lexicon that leaks is not a bug in a
feature, it is the product becoming something the PRD says it will not be.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.adapters.intent.heuristic import HeuristicIntentEngine
from anuvritti.adapters.intent.spoken import SpokenIntentEngine
from anuvritti.application.capture import (
    CaptureSparkCommand,
    CaptureSparkUseCase,
    OverrideFieldCommand,
    OverrideFieldUseCase,
)
from anuvritti.domain.family import Family, Member
from anuvritti.domain.lexicon import LexiconField
from anuvritti.domain.values import AttributionSource, IntentType, MemberRole, SourceKind, SourceRef
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import FamilyId, MemberId, SequentialIdGenerator
from tests.support.fakes import RecordingEventPublisher

NOW = datetime(2026, 3, 4, 19, 30, tzinfo=UTC)

#: A word no English lexicon in `heuristic.py` has an opinion about, which is the point:
#: whatever this Spark is filed under, the family put it there.
OURS = "sanskaar"


class Household:
    """One family, wired the way the container wires them."""

    def __init__(self, repos, family_id: FamilyId, owner_id: MemberId) -> None:
        self.repos = repos
        self.family_id = family_id
        self.owner_id = owner_id
        clock = FrozenClock(NOW)
        self.capture = CaptureSparkUseCase(
            families=repos.families,
            sparks=repos.sparks,
            intent_engine=SpokenIntentEngine(HeuristicIntentEngine()),
            events=RecordingEventPublisher(),
            clock=clock,
            ids=SequentialIdGenerator(f"spk-{owner_id}"),
            uow=repos.uow,
            lexicon=repos.lexicon,
        )
        self.override = OverrideFieldUseCase(
            sparks=repos.sparks,
            events=RecordingEventPublisher(),
            uow=repos.uow,
            clock=clock,
            lexicon=repos.lexicon,
        )

    def share(self, note: str):
        return self.capture.execute(
            CaptureSparkCommand(
                family_id=self.family_id,
                owner_id=self.owner_id,
                source=SourceRef(kind=SourceKind.TEXT, text=note),
                note=note,
            )
        ).unwrap()

    def correct(self, spark, to: IntentType):
        return self.override.execute(
            OverrideFieldCommand(spark_id=spark.id, field="intent", value=to)
        ).unwrap()

    def teach(self, note: str, means: IntentType, times: int = 2):
        for _ in range(times):
            self.correct(self.share(note), means)


@pytest.fixture
def household(repos, seeded_family: Family) -> Household:
    return Household(repos, seeded_family.id, seeded_family.members[0].id)


def _the_other_house(repos) -> Family:
    """A second family in the same database. The whole point of `TestNoFamilyHearsAnother`."""
    theirs = Family(
        id=FamilyId("fam-theirs"),
        name="The other house",
        members=(Member(MemberId("mem-theirs"), "Amma", MemberRole.PARENT),),
        children=(),
        created_at=NOW,
    )
    repos.families.save(theirs)
    return theirs


class TestACorrectionChangesTheNextCapture:
    def test_the_engine_has_no_opinion_about_a_family_word_to_begin_with(self, household):
        # The premise. If this ever starts passing for the wrong reason - because some
        # general lexicon learned the word - the tests below stop proving anything.
        first = household.share(f"{OURS} for the little one")
        assert first.intent.value is IntentType.REMEMBER

    def test_two_corrections_teach_it(self, household):
        household.teach(f"{OURS} for the little one", IntentType.TEACH)

        later = household.share(f"{OURS} again, a different one")

        assert later.intent.value is IntentType.TEACH

    def test_one_correction_does_not(self, household):
        household.teach(f"{OURS} for the little one", IntentType.TEACH, times=1)

        assert household.share(f"{OURS} again").intent.value is IntentType.REMEMBER

    def test_what_it_learned_is_still_only_a_guess(self, household):
        # The whole product rests on this. A family's own word is evidence, and evidence
        # is not a person saying so - the chip stays correctable and stays a guess.
        household.teach(f"{OURS} for the little one", IntentType.TEACH)

        later = household.share(f"{OURS} again")

        assert later.intent.source is AttributionSource.AI
        assert later.intent.human_override is False
        assert later.intent.confidence.value < 1.0

    def test_it_survives_a_restart(self, repos, household):
        # Held in the family's own archive, not in a process. Reading it back through a
        # fresh repository over the same file is the only honest way to check that.
        household.teach(f"{OURS} for the little one", IntentType.TEACH)

        reloaded = repos.lexicon.load(household.family_id).unwrap()

        assert reloaded.weights_for(LexiconField.INTENT, [OURS]) == {"TEACH": 1.0}

    def test_a_correction_the_parent_makes_stays_theirs(self, household):
        # The corrected Spark itself is never re-inferred; only the *next* one is helped.
        spark = household.share(f"{OURS} for the little one")
        corrected = household.correct(spark, IntentType.TEACH)

        assert corrected.intent.source is AttributionSource.HUMAN
        assert corrected.intent.human_override is True


class TestNoFamilyHearsAnother:
    def test_one_familys_words_never_reach_another(self, repos, seeded_family):
        theirs = _the_other_house(repos)

        ours = Household(repos, seeded_family.id, seeded_family.members[0].id)
        others = Household(repos, theirs.id, theirs.members[0].id)

        ours.teach(f"{OURS} for the little one", IntentType.TEACH)

        # The same word, in the same database, shared by the family next door.
        assert others.share(f"{OURS} again").intent.value is IntentType.REMEMBER

    def test_the_two_lexicons_are_separate_rows(self, repos, seeded_family):
        theirs = _the_other_house(repos)
        Household(repos, seeded_family.id, seeded_family.members[0].id).teach(
            f"{OURS} for the little one", IntentType.TEACH
        )

        assert len(repos.lexicon.load(seeded_family.id).unwrap()) > 0
        assert len(repos.lexicon.load(theirs.id).unwrap()) == 0


class TestTheFamilyKeepsIt:
    def test_deleting_the_family_takes_its_words(self, repos, household):
        household.teach(f"{OURS} for the little one", IntentType.TEACH)

        removed = repos.lexicon.delete_for_family(household.family_id).unwrap()

        assert removed > 0
        assert len(repos.lexicon.load(household.family_id).unwrap()) == 0

    def test_correcting_a_category_teaches_the_category_and_not_the_intent(self, household):
        spark = household.share(f"{OURS} for the little one")
        household.override.execute(
            OverrideFieldCommand(spark_id=spark.id, field="category", value="sanskaar")
        ).unwrap()
        household.override.execute(
            OverrideFieldCommand(
                spark_id=household.share(f"{OURS} again").id, field="category", value="sanskaar"
            )
        ).unwrap()

        lexicon = household.repos.lexicon.load(household.family_id).unwrap()

        assert lexicon.weights_for(LexiconField.CATEGORY, [OURS]) == {"sanskaar": 1.0}
        assert lexicon.weights_for(LexiconField.INTENT, [OURS]) == {}

    def test_correcting_an_age_teaches_nothing(self, household):
        # A family does not have private numbers. There is nothing transferable in it.
        from anuvritti.domain.values import AgeRange

        spark = household.share(f"{OURS} for the little one")
        household.override.execute(
            OverrideFieldCommand(spark_id=spark.id, field="age_range", value=AgeRange(4, 7))
        ).unwrap()

        assert len(household.repos.lexicon.load(household.family_id).unwrap()) == 0
