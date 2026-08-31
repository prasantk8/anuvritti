"""TASK-813 - Sealed Capsules Unit Tests (PRD 35, 8.5, 8.8)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.application.capsules import (
    CapsuleUseCase,
    SealAgeNCapsuleCommand,
    SealTheUnfinishedCommand,
)
from anuvritti.domain.capsule import CapsuleItem, CapsuleKind, CapsuleStatus
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import SourceRef
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import ChildId, FamilyId, MemberId, SequentialIdGenerator, SparkId
from tests.support.fakes import (
    InMemoryFamilyRepository,
    InMemorySparkRepository,
    RecordingEventPublisher,
    build_family,
)

FAMILY = FamilyId("fam-1")
CHILD = ChildId("ch-1")
PAPA = MemberId("mem-papa")
NOW = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)


@pytest.fixture
def harness():
    families = InMemoryFamilyRepository()
    families.save(build_family()).unwrap()
    sparks = InMemorySparkRepository()
    events = RecordingEventPublisher()
    clock = FrozenClock(NOW)
    ids = SequentialIdGenerator("cap")
    use_case = CapsuleUseCase(
        families=families,
        sparks=sparks,
        clock=clock,
        ids=ids,
        events=events,
    )
    return type(
        "Harness",
        (),
        {"families": families, "sparks": sparks, "events": events, "use_case": use_case},
    )()


class TestSealedCapsules:
    def test_seals_age_n_capsule_with_letters_and_media(self, harness):
        items = (
            CapsuleItem(item_id="item-1", title="A letter from Nani", media_id="med-letter-1"),
            CapsuleItem(
                item_id="item-2", title="The Year He Was Three Film", media_id="med-film-1"
            ),
        )
        capsule = harness.use_case.seal_age_n_capsule(
            SealAgeNCapsuleCommand(
                family_id=FAMILY,
                child_id=CHILD,
                author_id=PAPA,
                target_age_years=18,
                items=items,
            )
        ).unwrap()

        assert capsule.status is CapsuleStatus.SEALED
        assert capsule.kind is CapsuleKind.AGE_N
        assert capsule.target_age_years == 18
        assert len(capsule.items) == 2
        assert capsule.parent_view == "Sealed until age 18"
        assert "CapsuleSealed" in harness.events.names()

    def test_seals_the_unfinished_from_sparks_with_whys(self, harness):
        spark1 = Spark.capture(
            spark_id=SparkId("spk-1"),
            family_id=FAMILY,
            owner_id=PAPA,
            source=SourceRef.from_text("Camping under the Perseids", title="Perseids trip"),
            at=NOW,
            subject_child_id=CHILD,
        )
        spark1 = spark1.record_why(
            text="Because she asked where falling stars go.", at=NOW
        ).unwrap()
        harness.sparks.save(spark1).unwrap()

        capsule = harness.use_case.seal_the_unfinished(
            SealTheUnfinishedCommand(
                family_id=FAMILY,
                child_id=CHILD,
                author_id=PAPA,
                target_age_years=16,
            )
        ).unwrap()

        assert capsule.status is CapsuleStatus.SEALED
        assert capsule.kind is CapsuleKind.THE_UNFINISHED
        assert len(capsule.items) == 1
        assert capsule.items[0].why == "Because she asked where falling stars go."
        assert capsule.parent_view == "Sealed until age 16"
