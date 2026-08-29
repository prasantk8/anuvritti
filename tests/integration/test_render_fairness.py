"""TASK-1211: Render Backpressure & Fairness (PRD 44, PRD 8.2).

Verifies:
1. Anti-starvation: Heavy multi-year compiles do not block other families' quick clips.
2. Fair round-robin scheduling across multi-tenant families.
3. Queue backpressure ceiling per family prevents runaway queue exhaustion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import SqliteRenderJobRepository
from anuvritti.application.render_jobs import (
    JobStatus,
    SubmitRenderJobUseCase,
)
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate(conn)
    conn.execute(
        "INSERT INTO family (id, name, created_at) VALUES (?, ?, ?)",
        ("fam-A", "Family A", "2026-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO family (id, name, created_at) VALUES (?, ?, ?)",
        ("fam-B", "Family B", "2026-01-01T00:00:00Z"),
    )
    return conn


def test_anti_starvation_prioritizes_idle_family(db, tmp_path: Path):
    """Family B's pending job is claimed before Family A's backlogged jobs."""
    repo = SqliteRenderJobRepository(db)
    base_time = datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)
    clock = FrozenClock(base_time)
    submit = SubmitRenderJobUseCase(repo, clock=clock, max_queued_jobs=20)

    archive_a = tmp_path / "fam_a"
    archive_a.mkdir()
    archive_b = tmp_path / "fam_b"
    archive_b.mkdir()

    # 1. Family A submits 5 heavy jobs
    for i in range(5):
        clock.advance(seconds=1)
        submit.execute(
            family_id=FamilyId("fam-A"),
            child_id=ChildId("child-a"),
            spec_hash=f"hash-a-{i}",
            archive_path=archive_a,
        )

    # 2. Worker 1 claims Family A's first job (Family A now has 1 RUNNING job)
    clock.advance(seconds=1)
    job1 = repo.claim_next_pending(started_at=clock.now()).unwrap()
    assert job1 is not None
    assert job1.family_id == FamilyId("fam-A")
    assert job1.status == JobStatus.RUNNING

    # 3. Family B submits 1 quick 5-second voice snippet film
    clock.advance(seconds=1)
    submit.execute(
        family_id=FamilyId("fam-B"),
        child_id=ChildId("child-b"),
        spec_hash="hash-b-quick-voice",
        archive_path=archive_b,
    )

    # 4. Worker 2 claims next pending job: MUST pick Family B (0 running vs 1 running)
    clock.advance(seconds=1)
    job2 = repo.claim_next_pending(started_at=clock.now()).unwrap()
    assert job2 is not None
    assert job2.family_id == FamilyId("fam-B"), (
        "Fairness violation: Family B was starved behind Family A's queue"
    )
    assert job2.spec_hash == "hash-b-quick-voice"


def test_fair_round_robin_interleaving(db, tmp_path: Path):
    """When multiple families queue jobs, claims interleave fairly."""
    repo = SqliteRenderJobRepository(db)
    base_time = datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)
    clock = FrozenClock(base_time)
    submit = SubmitRenderJobUseCase(repo, clock=clock)

    archive = tmp_path / "archive"
    archive.mkdir()

    # Family A queues 3 jobs
    for i in range(3):
        clock.advance(seconds=1)
        submit.execute(
            family_id=FamilyId("fam-A"),
            child_id=ChildId("child-a"),
            spec_hash=f"spec-a-{i}",
            archive_path=archive,
        )

    # Family B queues 3 jobs
    for i in range(3):
        clock.advance(seconds=1)
        submit.execute(
            family_id=FamilyId("fam-B"),
            child_id=ChildId("child-b"),
            spec_hash=f"spec-b-{i}",
            archive_path=archive,
        )

    # Workers claim jobs one by one (simulating concurrent workers)
    claimed_families = []
    for _ in range(6):
        clock.advance(seconds=1)
        job = repo.claim_next_pending(started_at=clock.now()).unwrap()
        assert job is not None
        claimed_families.append(str(job.family_id))

    # Expect balanced interleaving between Family A and Family B
    assert claimed_families == ["fam-A", "fam-B", "fam-A", "fam-B", "fam-A", "fam-B"]


def test_queue_backpressure_enforces_capacity_limit(db, tmp_path: Path):
    """Submitting jobs beyond max_queued_jobs returns TOO_MANY_REQUESTS refusal."""
    repo = SqliteRenderJobRepository(db)
    submit = SubmitRenderJobUseCase(repo, max_queued_jobs=3)

    archive = tmp_path / "archive"
    archive.mkdir()

    # Submit 3 jobs (allowed)
    for i in range(3):
        res = submit.execute(
            family_id=FamilyId("fam-A"),
            child_id=ChildId("child-a"),
            spec_hash=f"hash-{i}",
            archive_path=archive,
        )
        assert res.is_ok()

    # 4th submission must be refused with backpressure error
    res4 = submit.execute(
        family_id=FamilyId("fam-A"),
        child_id=ChildId("child-a"),
        spec_hash="hash-4-overflow",
        archive_path=archive,
    )
    assert res4.is_err()
    error = res4.unwrap_err()
    assert error.code == ErrorCode.TOO_MANY_REQUESTS
    assert "queued" in error.message.lower()

    # But Family B can still submit within their own quota
    res_b = submit.execute(
        family_id=FamilyId("fam-B"),
        child_id=ChildId("child-b"),
        spec_hash="hash-b-1",
        archive_path=archive,
    )
    assert res_b.is_ok()
