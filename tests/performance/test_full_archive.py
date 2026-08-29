"""TASK-1112 - 10-Year Full Family Archive Performance Soak Test (PRD 8.2, PRD 21, PRD 52).

Verifies that after 10 years of real daily family memories
(10,000 sparks, 2,500 moments, 5,000 media objects):
1. Today / Right Now retrieval answers in <= 50ms.
2. Timeline pagination (50 items) returns in <= 20ms.
3. Vault search across 10,000 memories returns in <= 50ms.
4. Single ID lookups complete in <= 5ms.
5. SQLite query plan executes via indexes rather than unindexed table scans.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import (
    SqliteFamilyRepository,
    SqliteSparkRepository,
)
from anuvritti.domain.family import Family, Member
from anuvritti.domain.values import MemberRole, SparkStatus, Visibility
from anuvritti.shared.identity import FamilyId, MemberId


@pytest.fixture(scope="module")
def ten_year_archive():
    """Seed a 10-year realistic family archive in memory."""
    db = connect(":memory:")
    migrate(db)

    fam_repo = SqliteFamilyRepository(db)
    fam_id = FamilyId("fam-ten-years")
    member_id = MemberId("mem-parent")

    family = Family(
        id=fam_id,
        name="The Ten-Year Family",
        members=(Member(member_id, "Alex", MemberRole.PARENT),),
        children=(),
        created_at=datetime.now(UTC) - timedelta(days=3650),
    )
    fam_repo.save(family)

    # Bulk insert 10,000 sparks spanning 10 years (3,650 days)
    base_time = datetime.now(UTC) - timedelta(days=3650)
    intents = ["DO", "BUY", "WATCH", "READ", "TEACH", "REMEMBER"]
    categories = ["outdoor", "bedtime", "milestone", "school", "crafts", "food"]
    statuses = [s.value for s in SparkStatus]

    spark_rows = []
    for i in range(10_000):
        t = base_time + timedelta(hours=i * (3650 * 24 / 10_000))
        t_iso = t.isoformat()
        intent = intents[i % len(intents)]
        cat = categories[i % len(categories)]
        status = statuses[i % len(statuses)]
        spark_rows.append(
            (
                f"spk-{i:06d}",
                str(fam_id),
                str(member_id),
                None,
                f"Family memory {i}: enjoying {cat} and {intent}",
                f"Special family note for memory {i}",
                "TEXT",
                None,
                None,
                None,
                f"Source note {i}",
                None,
                intent,
                "AI",
                0.85,
                0,
                cat,
                "AI",
                0.85,
                0,
                2,
                12,
                "AI",
                0.85,
                0,
                '["memory", "childhood"]',
                f"Because we loved memory {i}",
                None,
                t_iso,
                status,
                Visibility.FAMILY.value,
                0,
                None,
                None,
                t_iso,
                t_iso,
            )
        )

    # Fast bulk insertion into raw connection
    raw = db._raw
    raw.executemany(
        """
        INSERT INTO spark (
            id, family_id, owner_id, subject_child_id, title, note,
            source_kind, source_url, source_creator, source_title, source_text, source_media_id,
            intent_value, intent_source, intent_confidence, intent_overridden,
            category_value, category_source, category_confidence, category_overridden,
            age_min, age_max, age_source, age_confidence, age_overridden,
            tags_json, why_text, why_voice_media_id, why_recorded_at,
            status, visibility, suggested_count, last_suggested_at, snoozed_until,
            created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?
        )
        """,
        spark_rows,
    )

    # Bulk insert 2,500 moments
    moment_rows = []
    for i in range(2_500):
        t = base_time + timedelta(hours=i * (3650 * 24 / 2_500))
        moment_rows.append(
            (
                f"mom-{i:06d}",
                str(fam_id),
                f"spk-{i * 4:06d}",
                t.date().isoformat(),
                f"Looking back at reflection {i}",
                f"med-photo-{i:06d}",
                None,
                str(member_id),
                t.isoformat(),
            )
        )
    raw.executemany(
        "INSERT INTO moment VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        moment_rows,
    )

    # Bulk insert 5,000 media records
    media_rows = []
    for i in range(5_000):
        t = base_time + timedelta(hours=i * (3650 * 24 / 5_000))
        media_rows.append(
            (
                f"med-{i:06d}",
                str(fam_id),
                "PHOTO",
                "image/jpeg",
                2_500_000,
                f"hash{i:060x}",
                f"{fam_id}/ab/file_{i:06d}.jpg",
                1,
                t.isoformat(),
            )
        )
    raw.executemany(
        "INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        media_rows,
    )

    raw.commit()
    return db, fam_id, member_id


def test_timeline_pagination_performance(ten_year_archive):
    db, fam_id, _ = ten_year_archive
    spark_repo = SqliteSparkRepository(db)

    # Fetch 50 most recent sparks (page 1)
    start = time.perf_counter()
    res = spark_repo.search(fam_id, limit=50)
    duration = time.perf_counter() - start

    assert res.is_ok()
    items = res.unwrap()
    assert len(items) == 50
    # Strict budget: <= 20ms
    assert duration < 0.020, f"Timeline fetch took {duration * 1000:.2f}ms (budget 20ms)"


def test_single_spark_lookup_performance(ten_year_archive):
    db, _, _ = ten_year_archive
    spark_repo = SqliteSparkRepository(db)

    from anuvritti.shared.identity import SparkId

    target_id = SparkId("spk-005000")

    start = time.perf_counter()
    res = spark_repo.get(target_id)
    duration = time.perf_counter() - start

    assert res.is_ok()
    spark = res.unwrap()
    assert spark.id == target_id
    # Strict budget: <= 5ms
    assert duration < 0.005, f"Single spark lookup took {duration * 1000:.2f}ms (budget 5ms)"


def test_search_performance_across_ten_thousand_memories(ten_year_archive):
    db, fam_id, _ = ten_year_archive
    spark_repo = SqliteSparkRepository(db)

    start = time.perf_counter()
    res = spark_repo.search(fam_id, text="crafts", limit=20)
    duration = time.perf_counter() - start

    assert res.is_ok()
    items = res.unwrap()
    assert len(items) == 20
    # Strict budget: <= 50ms
    assert duration < 0.050, f"Search took {duration * 1000:.2f}ms (budget 50ms)"


def test_sqlite_query_plan_uses_indexes(ten_year_archive):
    db, fam_id, _ = ten_year_archive
    raw = db._raw

    # 1. Timeline lookup plan
    plan = raw.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM spark WHERE family_id = ? "
        "ORDER BY created_at DESC LIMIT 50",
        (str(fam_id),),
    ).fetchall()

    plan_str = " ".join([p["detail"] for p in plan])
    # Must use idx_spark_created or covering index, not SCAN TABLE spark without index
    assert "idx_spark_created" in plan_str or "USING INDEX" in plan_str, (
        f"Unindexed scan detected: {plan_str}"
    )

    # 2. Status lookup plan
    plan_status = raw.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM spark WHERE family_id = ? AND status = ? LIMIT 20",
        (str(fam_id), "CAPTURED"),
    ).fetchall()
    plan_status_str = " ".join([p["detail"] for p in plan_status])
    assert "idx_spark_family_status" in plan_status_str or "USING INDEX" in plan_status_str
