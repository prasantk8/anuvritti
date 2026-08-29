"""TASK-1101 - Rehearsed schema migrations (HARDENING 5.4, PRD 8.6).

Verifies forward migration, rehearsed rollback, data preservation across version changes,
and the safety guarantee that a failing migration leaves the live database completely
untouched.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from anuvritti.adapters.persistence.migrations import (
    get_version,
    migrate_to,
    rehearse_and_migrate,
)
from anuvritti.adapters.persistence.schema import SCHEMA_VERSION, connect
from anuvritti.adapters.persistence.sqlite import (
    SqliteFamilyRepository,
    SqliteMomentRepository,
    SqliteSparkRepository,
)
from anuvritti.domain.family import ChildProfile, Family, Member
from anuvritti.domain.moment import Moment
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import MemberRole, SourceRef
from anuvritti.shared.identity import ChildId, FamilyId, MemberId, MomentId, SparkId


def test_forward_and_backward_migration_lifecycle(tmp_path: Path):
    db_path = tmp_path / "lifecycle.db"
    conn = connect(str(db_path))

    assert get_version(conn) == 0

    # 1. Step forwards version by version
    for target in range(1, SCHEMA_VERSION + 1):
        res = migrate_to(conn, target)
        assert res.is_ok()
        assert get_version(conn) == target

    # Verify tables exist at v4
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"family", "spark", "moment", "device", "voice_note", "lexicon_term"} <= tables

    # 2. Step backwards version by version
    for target in range(SCHEMA_VERSION - 1, -1, -1):
        res = migrate_to(conn, target)
        assert res.is_ok()
        assert get_version(conn) == target

    # At v0, all tables dropped
    tables_v0 = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    assert len(tables_v0) == 0

    conn.close()


def test_data_preservation_across_migration_and_rollback(tmp_path: Path):
    db_path = tmp_path / "family_archive.db"
    conn = connect(str(db_path))

    # Migrate to v1
    migrate_to(conn, 1).unwrap()

    family_id = FamilyId("fam-001")
    parent_id = MemberId("mem-001")
    child_id = ChildId("child-001")
    spark_id = SparkId("spark-001")
    moment_id = MomentId("moment-001")
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    # Seed data in v1
    families = SqliteFamilyRepository(conn)
    sparks = SqliteSparkRepository(conn)
    moments = SqliteMomentRepository(conn)

    family = Family(
        id=family_id,
        name="The Explorers",
        members=(Member(parent_id, "Papa", MemberRole.PARENT),),
        children=(ChildProfile(child_id, parent_id, "Leo", date(2022, 5, 14)),),
        created_at=now,
    )
    families.save(family)

    spark = Spark.capture(
        spark_id=spark_id,
        family_id=family_id,
        owner_id=parent_id,
        source=SourceRef.from_text("Building a campfire"),
        at=now,
        subject_child_id=child_id,
    )
    sparks.save(spark)

    moment = Moment.create(
        moment_id=moment_id,
        family_id=family_id,
        spark_id=spark_id,
        created_by=parent_id,
        spark_captured_at=now,
        at=now,
        happened_on=now.date(),
        reflection="Built the fire and roasted marshmallows",
    ).unwrap()
    moments.save(moment)

    # Migrate forward to v4
    migrate_to(conn, 4).unwrap()
    assert get_version(conn) == 4

    # Add a lexicon term in v4
    conn.execute(
        "INSERT INTO lexicon_term (family_id, field, term, means, times, last_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (str(family_id), "category", "marshmallows", "camping", 1, now.isoformat()),
    )

    # Roll back to v3 (lexicon_term dropped)
    migrate_to(conn, 3).unwrap()
    assert get_version(conn) == 3

    # Verify v1 data is still 100% intact and queryable!
    f_check = families.get(family_id).unwrap()
    assert f_check.name == "The Explorers"

    s_check = sparks.get(spark_id).unwrap()
    assert s_check.title == "Building a campfire"

    m_check = moments.get(moment_id).unwrap()
    assert m_check.reflection == "Built the fire and roasted marshmallows"

    # Migrate forward again to v4
    migrate_to(conn, 4).unwrap()
    assert get_version(conn) == 4

    conn.close()


def test_rehearse_and_migrate_aborts_and_protects_live_database_on_failure(tmp_path: Path):
    live_db = tmp_path / "live_archive.db"
    conn = connect(str(live_db))
    migrate_to(conn, 2).unwrap()

    # Seed data
    families = SqliteFamilyRepository(conn)
    family_id = FamilyId("fam-protected")
    families.save(
        Family(
            id=family_id,
            name="Protected Family",
            members=(Member(MemberId("m1"), "Mama", MemberRole.PARENT),),
            children=(),
            created_at=datetime(2026, 8, 29, tzinfo=UTC),
        )
    )
    conn.close()

    # Attempt migration to an invalid / impossible version
    res = rehearse_and_migrate(live_db, target_version=99)
    assert res.is_err()

    # Live database is completely untouched at version 2
    check_conn = connect(str(live_db))
    assert get_version(check_conn) == 2
    f_res = SqliteFamilyRepository(check_conn).get(family_id).unwrap()
    assert f_res.name == "Protected Family"
    check_conn.close()


def test_rehearse_and_migrate_succeeds_on_valid_path(tmp_path: Path):
    live_db = tmp_path / "live_archive_ok.db"
    conn = connect(str(live_db))
    migrate_to(conn, 1).unwrap()
    conn.close()

    res = rehearse_and_migrate(live_db, target_version=4)
    assert res.is_ok()
    assert res.unwrap() == 4

    check_conn = connect(str(live_db))
    assert get_version(check_conn) == 4
    check_conn.close()
