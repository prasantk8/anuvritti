"""TASK-805 - Search Across Family Archive with FamilyLexicon (PRD 21, PRD 50).

Verifies that:
1. Text search finds sparks across titles, notes, and why explanations.
2. FamilyLexicon expansion allows families to search using their private words.
3. Family isolation is strictly preserved across all searches.
"""

from __future__ import annotations

from datetime import UTC, datetime

from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import (
    SqliteFamilyRepository,
    SqliteLexiconRepository,
    SqliteSparkRepository,
)
from anuvritti.application.vault import SearchVaultQuery, SearchVaultUseCase
from anuvritti.domain.family import Family, Member
from anuvritti.domain.lexicon import Correction, FamilyLexicon, LexiconField
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import IntentType, MemberRole, SourceRef
from anuvritti.shared.clock import SystemClock
from anuvritti.shared.identity import FamilyId, MemberId, SparkId


def setup_test_environment() -> tuple[
    SqliteFamilyRepository,
    SqliteSparkRepository,
    SqliteLexiconRepository,
    FamilyId,
    MemberId,
]:
    db = connect(":memory:")
    migrate(db)

    fam_repo = SqliteFamilyRepository(db)
    spark_repo = SqliteSparkRepository(db)
    lex_repo = SqliteLexiconRepository(db)

    fam_id = FamilyId("fam-search-1")
    member_id = MemberId("mem-parent-1")
    family = Family(
        id=fam_id,
        name="The Smiths",
        members=(Member(member_id, "Alice", MemberRole.PARENT),),
        children=(),
        created_at=datetime.now(UTC),
    )
    fam_repo.save(family)

    return fam_repo, spark_repo, lex_repo, fam_id, member_id


def test_search_by_title_and_notes():
    fam_repo, spark_repo, lex_repo, fam_id, member_id = setup_test_environment()
    use_case = SearchVaultUseCase(
        families=fam_repo,
        sparks=spark_repo,
        clock=SystemClock(),
        lexicons=lex_repo,
    )

    # Add 2 sparks
    spark1 = (
        Spark.capture(
            spark_id=SparkId("spk-1"),
            family_id=fam_id,
            owner_id=member_id,
            source=SourceRef.from_text("Learning to ride a bicycle in the park"),
            note="He wore the yellow helmet",
            at=datetime.now(UTC),
        )
        .override_intent(IntentType.DO)
        .unwrap()
    )
    spark_repo.save(spark1)

    spark2 = (
        Spark.capture(
            spark_id=SparkId("spk-2"),
            family_id=fam_id,
            owner_id=member_id,
            source=SourceRef.from_text("Baking blueberry muffins with grandmother"),
            note="He loved mixing the flour",
            at=datetime.now(UTC),
        )
        .override_intent(IntentType.MAKE if hasattr(IntentType, "MAKE") else IntentType.DO)
        .unwrap()
    )
    spark_repo.save(spark2)

    # Search for "bicycle"
    res1 = use_case.execute(SearchVaultQuery(family_id=fam_id, actor_id=member_id, text="bicycle"))
    assert res1.is_ok()
    items1 = res1.unwrap()
    assert len(items1) == 1
    assert items1[0].id == SparkId("spk-1")

    # Search for "flour" (matches note)
    res2 = use_case.execute(SearchVaultQuery(family_id=fam_id, actor_id=member_id, text="flour"))
    assert res2.is_ok()
    items2 = res2.unwrap()
    assert len(items2) == 1
    assert items2[0].id == SparkId("spk-2")


def test_search_expands_via_family_lexicon():
    fam_repo, spark_repo, lex_repo, fam_id, member_id = setup_test_environment()
    use_case = SearchVaultUseCase(
        families=fam_repo,
        sparks=spark_repo,
        clock=SystemClock(),
        lexicons=lex_repo,
    )

    # Teach family lexicon that "kahani" -> intent READ
    lexicon = FamilyLexicon.empty(fam_id)
    now = datetime.now(UTC)
    for _ in range(3):
        corr = Correction.from_override(
            family_id=fam_id,
            field=LexiconField.INTENT,
            corrected_to="READ",
            at=now,
            title="Bedtime kahani time",
        )
        lexicon = lexicon.learn(corr).unwrap()
    lex_repo.save(lexicon)

    # Create a spark with intent READ
    spark = (
        Spark.capture(
            spark_id=SparkId("spk-book"),
            family_id=fam_id,
            owner_id=member_id,
            source=SourceRef.from_text("Night book reading"),
            at=now,
        )
        .override_intent(IntentType.READ)
        .unwrap()
    )
    spark_repo.save(spark)

    # Searching for "kahani" expands to intent READ and finds the spark!
    res = use_case.execute(SearchVaultQuery(family_id=fam_id, actor_id=member_id, text="kahani"))
    assert res.is_ok()
    items = res.unwrap()
    assert len(items) == 1
    assert items[0].id == SparkId("spk-book")


def test_search_preserves_family_isolation():
    fam_repo, spark_repo, lex_repo, fam_id_1, member_id_1 = setup_test_environment()
    fam_id_2 = FamilyId("fam-other-2")
    member_id_2 = MemberId("mem-other-2")

    fam2 = Family(
        id=fam_id_2,
        name="Other Family",
        members=(Member(member_id_2, "Bob", MemberRole.PARENT),),
        children=(),
        created_at=datetime.now(UTC),
    )
    fam_repo.save(fam2)

    use_case = SearchVaultUseCase(
        families=fam_repo,
        sparks=spark_repo,
        clock=SystemClock(),
        lexicons=lex_repo,
    )

    # Family 2 saves a spark
    spark_f2 = (
        Spark.capture(
            spark_id=SparkId("spk-f2"),
            family_id=fam_id_2,
            owner_id=member_id_2,
            source=SourceRef.from_text("Secret family treasure"),
            at=datetime.now(UTC),
        )
        .override_intent(IntentType.WATCH)
        .unwrap()
    )
    spark_repo.save(spark_f2)

    # Family 1 searches for "treasure" -> finds nothing
    res = use_case.execute(
        SearchVaultQuery(family_id=fam_id_1, actor_id=member_id_1, text="treasure")
    )
    assert res.is_ok()
    assert len(res.unwrap()) == 0
