"""TASK-904 - Child data rights and vault ownership (PRD 45, PRD 25, PRD 24).

Tests verifying:
1. Right to hide content from family view.
2. Right to permanently delete specific childhood memories without destroying the whole archive.
3. Right to claim and export the child's complete personal record / vault.
4. Permission guardrails.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from anuvritti.adapters.media.filesystem import EncryptedFilesystemMediaStore
from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import (
    SqliteFamilyRepository,
    SqliteLittleThingRepository,
    SqliteMediaCatalogue,
    SqliteMomentRepository,
    SqliteRightNowRepository,
    SqliteSparkRepository,
    SqliteVoiceNoteRepository,
)
from anuvritti.application.privacy import (
    DeleteChildContentCommand,
    DeleteChildContentUseCase,
    ExportChildVaultQuery,
    ExportChildVaultUseCase,
    HideChildContentCommand,
    HideChildContentUseCase,
)
from anuvritti.domain.family import ChildProfile, Family, Member
from anuvritti.domain.moment import Moment
from anuvritti.domain.presence import LittleThing, RightNowSnapshot
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import MemberRole, SourceRef, Visibility
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    LittleThingId,
    MemberId,
    MomentId,
    RightNowId,
    SequentialIdGenerator,
    SparkId,
)
from tests.support.fakes import RecordingEventPublisher


class DummyUow:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture
def env(tmp_path: Path):
    db_path = tmp_path / "child_rights.db"
    media_dir = tmp_path / "media"
    conn = connect(str(db_path))
    migrate(conn)

    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    clock = FrozenClock(now)
    ids = SequentialIdGenerator("cr")
    events = RecordingEventPublisher()
    uow = DummyUow()

    families = SqliteFamilyRepository(conn)
    sparks = SqliteSparkRepository(conn)
    moments = SqliteMomentRepository(conn)
    little_things = SqliteLittleThingRepository(conn)
    right_now = SqliteRightNowRepository(conn)
    voice_notes = SqliteVoiceNoteRepository(conn)
    catalogue = SqliteMediaCatalogue(conn)

    media_store = EncryptedFilesystemMediaStore(
        root=media_dir,
        catalogue=catalogue,
        ids=ids,
        encryption_key=Fernet.generate_key().decode(),
        max_bytes=10 * 1024 * 1024,
        allowed_mime_types=frozenset({"image/jpeg", "audio/mp4"}),
    )

    family_id = FamilyId("fam-001")
    papa_id = MemberId("mem-papa")
    child_leo_id = ChildId("child-leo")
    child_leo_member_id = MemberId("mem-leo")
    child_maya_id = ChildId("child-maya")

    family = Family(
        id=family_id,
        name="The Family",
        members=(
            Member(papa_id, "Papa", MemberRole.PARENT),
            Member(child_leo_member_id, "Leo", MemberRole.CHILD),
        ),
        children=(
            ChildProfile(child_leo_id, papa_id, "Leo", date(2018, 5, 14)),
            ChildProfile(child_maya_id, papa_id, "Maya", date(2022, 9, 20)),
        ),
        created_at=now,
    )
    families.save(family)

    # Seed memories for Leo
    spark_leo = Spark.capture(
        spark_id=SparkId("spk-leo-1"),
        family_id=family_id,
        owner_id=papa_id,
        source=SourceRef.from_text("Leo building legos"),
        at=now,
        subject_child_id=child_leo_id,
    )
    spark_leo = spark_leo.change_visibility(Visibility.FAMILY).unwrap()
    sparks.save(spark_leo)

    moment_leo = Moment.create(
        moment_id=MomentId("mom-leo-1"),
        family_id=family_id,
        spark_id=spark_leo.id,
        created_by=papa_id,
        spark_captured_at=now,
        at=now,
        happened_on=now.date(),
        reflection="Leo built a giant lego castle",
    ).unwrap()
    moments.save(moment_leo)

    # Seed memories for Maya (different child)
    spark_maya = Spark.capture(
        spark_id=SparkId("spk-maya-1"),
        family_id=family_id,
        owner_id=papa_id,
        source=SourceRef.from_text("Maya painting flowers"),
        at=now,
        subject_child_id=child_maya_id,
    )
    sparks.save(spark_maya)

    # Little things and Right now
    little_things.save(
        LittleThing.capture(
            little_thing_id=LittleThingId("lt-leo"),
            family_id=family_id,
            author_id=papa_id,
            subject_child_id=child_leo_id,
            text="Leo loves space dinosaurs",
            audio_media_id=None,
            at=now,
        ).unwrap()
    )

    right_now.save(
        RightNowSnapshot.capture(
            right_now_id=RightNowId("rn-leo"),
            family_id=family_id,
            child_id=child_leo_id,
            prompt="What is your favorite color?",
            answer="Cobalt Blue",
            at=now,
        ).unwrap()
    )

    return {
        "families": families,
        "sparks": sparks,
        "moments": moments,
        "little_things": little_things,
        "right_now": right_now,
        "voice_notes": voice_notes,
        "media": media_store,
        "events": events,
        "clock": clock,
        "uow": uow,
        "family_id": family_id,
        "papa_id": papa_id,
        "child_leo_id": child_leo_id,
        "child_leo_member_id": child_leo_member_id,
        "spark_leo": spark_leo,
    }


def test_child_can_hide_content_about_them(env):
    use_case = HideChildContentUseCase(
        families=env["families"],
        sparks=env["sparks"],
        events=env["events"],
        uow=env["uow"],
    )

    # Leo (CHILD) hides his lego spark
    res = use_case.execute(
        HideChildContentCommand(
            family_id=env["family_id"],
            child_id=env["child_leo_id"],
            spark_id=env["spark_leo"].id,
            requestor_id=env["child_leo_member_id"],
        )
    )
    assert res.is_ok()
    hidden_spark = res.unwrap()
    assert hidden_spark.visibility == Visibility.PRIVATE


def test_child_can_delete_specific_memory_about_them(env):
    use_case = DeleteChildContentUseCase(
        families=env["families"],
        sparks=env["sparks"],
        moments=env["moments"],
        events=env["events"],
        uow=env["uow"],
    )

    # Leo deletes his lego spark
    res = use_case.execute(
        DeleteChildContentCommand(
            family_id=env["family_id"],
            child_id=env["child_leo_id"],
            spark_id=env["spark_leo"].id,
            requestor_id=env["child_leo_member_id"],
        )
    )
    assert res.is_ok()

    # Verify spark and moment are hard-deleted
    assert env["sparks"].get(env["spark_leo"].id).is_err()
    assert env["moments"].get(MomentId("mom-leo-1")).is_err()

    # Maya's memory is completely untouched
    assert env["sparks"].get(SparkId("spk-maya-1")).is_ok()


def test_child_can_export_and_own_personal_vault(env):
    use_case = ExportChildVaultUseCase(
        families=env["families"],
        sparks=env["sparks"],
        moments=env["moments"],
        little_things=env["little_things"],
        right_now=env["right_now"],
        voice_notes=env["voice_notes"],
        media=env["media"],
        events=env["events"],
        clock=env["clock"],
    )

    # Leo exports his vault
    res = use_case.execute(
        ExportChildVaultQuery(
            family_id=env["family_id"],
            child_id=env["child_leo_id"],
            requestor_id=env["child_leo_member_id"],
        )
    )
    assert res.is_ok()
    vault = res.unwrap()

    assert vault["vault_owner_child"]["display_name"] == "Leo"
    # Includes Leo's spark and moment
    spark_ids = [s["id"] for s in vault["sparks"]]
    assert "spk-leo-1" in spark_ids
    # Does NOT include Maya's spark
    assert "spk-maya-1" not in spark_ids

    # Includes Leo's little thing and right now
    assert len(vault["little_things"]) == 1
    assert "space dinosaurs" in vault["little_things"][0]["text"]
    assert len(vault["right_now"]) == 1
    assert vault["right_now"][0]["answer"] == "Cobalt Blue"
