"""TASK-1201: Compilation as a durable job.

Submitted, resumable, and idempotent on the hash of the spec, so a retry is never a second film.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import SqliteRenderJobRepository
from anuvritti.application.ports import RenderedFilm, RenderedFrame
from anuvritti.application.render_jobs import (
    CancelRenderJobUseCase,
    GetRenderJobUseCase,
    JobStatus,
    RenderJobWorker,
    SubmitRenderJobUseCase,
)
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId
from anuvritti.shared.result import Err, Ok, Result


class _FixedClock:
    def __init__(self, t: datetime) -> None:
        self._t = t

    def now(self) -> datetime:
        return self._t

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._t += timedelta(seconds=seconds)


class _SequentialIds:
    def __init__(self, prefix: str = "job") -> None:
        self._counter = 0
        self._prefix = prefix

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._prefix}-{self._counter}"


class _FakeRenderer:
    def __init__(self, *, succeed: bool = True, error_msg: str = "render failure") -> None:
        self.succeed = succeed
        self.error_msg = error_msg
        self.rendered_archives: list[Path] = []

    def render(self, archive: Path, *, destination: Path) -> Result[RenderedFilm, DomainError]:
        self.rendered_archives.append(archive)
        if not self.succeed:
            return Err(DomainError(ErrorCode.FILM_NOT_COMPILABLE, self.error_msg))

        manifest = destination.with_suffix(".manifest.json")
        frame = RenderedFrame(
            "scene-1", destination.parent / "f.png", destination.parent / "d.html"
        )
        return Ok(RenderedFilm(destination, manifest, (frame,), 12.5))


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate(conn)
    # Seed a family
    conn.execute(
        "INSERT INTO family (id, name, created_at) VALUES (?, ?, ?)",
        ("fam-1", "The Smiths", "2026-01-01T00:00:00Z"),
    )
    return conn


def test_submit_render_job_and_retrieve(db, tmp_path: Path):
    repo = SqliteRenderJobRepository(db)
    clock = _FixedClock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    ids = _SequentialIds()
    submit = SubmitRenderJobUseCase(repo, clock=clock, ids=ids)
    get_job = GetRenderJobUseCase(repo)

    archive_dir = tmp_path / "export_archive"
    archive_dir.mkdir()

    res = submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="abc123hash",
        archive_path=archive_dir,
    )
    assert res.is_ok()
    job, created = res.unwrap()
    assert created is True
    assert job.id == "job-1"
    assert job.status == JobStatus.PENDING
    assert job.spec_hash == "abc123hash"
    assert job.progress_percent == 0.0

    # Retrieve
    fetched = get_job.execute("job-1")
    assert fetched.is_ok()
    assert fetched.unwrap().id == "job-1"
    assert fetched.unwrap().spec_hash == "abc123hash"


def test_idempotency_on_spec_hash(db, tmp_path: Path):
    """Submitting the same spec_hash returns the existing job and never spawns a duplicate."""
    repo = SqliteRenderJobRepository(db)
    clock = _FixedClock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    ids = _SequentialIds()
    submit = SubmitRenderJobUseCase(repo, clock=clock, ids=ids)

    archive = tmp_path / "export"
    archive.mkdir()

    res1 = submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="spec-sha256-xyz",
        archive_path=archive,
    )
    assert res1.is_ok()
    job1, created1 = res1.unwrap()
    assert created1 is True
    assert job1.id == "job-1"

    # Second submission with same spec hash
    res2 = submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="spec-sha256-xyz",
        archive_path=archive,
    )
    assert res2.is_ok()
    job2, created2 = res2.unwrap()
    assert created2 is False
    assert job2.id == "job-1"  # Returns first job, does not create job-2!

    # Verify database has exactly 1 row
    jobs_list = repo.list_for_family(FamilyId("fam-1")).unwrap()
    assert len(jobs_list) == 1


def test_worker_lifecycle_success(db, tmp_path: Path):
    """Worker picks up pending job, renders film, updates to COMPLETED with manifest."""
    repo = SqliteRenderJobRepository(db)
    clock = _FixedClock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    ids = _SequentialIds()
    submit = SubmitRenderJobUseCase(repo, clock=clock, ids=ids)

    archive = tmp_path / "export"
    archive.mkdir()
    dest = tmp_path / "output" / "film.mp4"

    submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="spec-hash-1",
        archive_path=archive,
        output_path=dest,
    )

    renderer = _FakeRenderer(succeed=True)
    worker = RenderJobWorker(repo, renderer, clock=clock)

    clock.advance(10.0)
    result = worker.process_next()
    assert result.is_ok()
    job = result.unwrap()
    assert job is not None
    assert job.status == JobStatus.COMPLETED
    assert job.output_path == dest
    assert job.manifest_path == dest.with_suffix(".manifest.json")
    assert job.progress_percent == 100.0
    assert job.started_at is not None
    assert job.completed_at is not None
    assert len(renderer.rendered_archives) == 1

    # An identical submission after completion still returns completed job (idempotent result)
    res_retry = submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="spec-hash-1",
        archive_path=archive,
    )
    assert res_retry.is_ok()
    job_retry, created_retry = res_retry.unwrap()
    assert created_retry is False
    assert job_retry.id == job.id
    assert job_retry.status == JobStatus.COMPLETED


def test_worker_lifecycle_failure(db, tmp_path: Path):
    """When rendering fails, job is marked FAILED with error message."""
    repo = SqliteRenderJobRepository(db)
    clock = _FixedClock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    ids = _SequentialIds()
    submit = SubmitRenderJobUseCase(repo, clock=clock, ids=ids)

    archive = tmp_path / "export"
    archive.mkdir()

    submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="spec-hash-bad",
        archive_path=archive,
    )

    renderer = _FakeRenderer(succeed=False, error_msg="audio sync failed")
    worker = RenderJobWorker(repo, renderer, clock=clock)

    result = worker.process_next()
    assert result.is_ok()
    job = result.unwrap()
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.error_message == "audio sync failed"


def test_resumable_crash_recovery(db, tmp_path: Path):
    """If a worker crashes while a job is RUNNING, recover_interrupted_jobs resets it to PENDING."""
    repo = SqliteRenderJobRepository(db)
    clock = _FixedClock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    ids = _SequentialIds()
    submit = SubmitRenderJobUseCase(repo, clock=clock, ids=ids)

    archive = tmp_path / "export"
    archive.mkdir()

    submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="crash-hash",
        archive_path=archive,
    )

    # Claim the job to make it RUNNING
    claimed = repo.claim_next_pending(started_at=clock.now()).unwrap()
    assert claimed is not None
    assert claimed.status == JobStatus.RUNNING

    # Simulate worker crash & reboot
    renderer = _FakeRenderer(succeed=True)
    new_worker = RenderJobWorker(repo, renderer, clock=clock)

    recovered_count = new_worker.recover_interrupted_jobs().unwrap()
    assert recovered_count == 1

    # Check job is now PENDING again
    job = repo.get(claimed.id).unwrap()
    assert job is not None
    assert job.status == JobStatus.PENDING

    # Now the new worker can resume and finish it
    res = new_worker.process_next()
    assert res.is_ok()
    assert res.unwrap().status == JobStatus.COMPLETED


def test_cancellation(db, tmp_path: Path):
    """Job cancellation sets status to CANCELLED."""
    repo = SqliteRenderJobRepository(db)
    clock = _FixedClock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    ids = _SequentialIds()
    submit = SubmitRenderJobUseCase(repo, clock=clock, ids=ids)
    cancel = CancelRenderJobUseCase(repo)

    archive = tmp_path / "export"
    archive.mkdir()

    res = submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="spec-to-cancel",
        archive_path=archive,
    )
    job = res.unwrap()[0]

    cancel_res = cancel.execute(job.id)
    assert cancel_res.is_ok()
    assert cancel_res.unwrap() is True

    # Check status
    updated = repo.get(job.id).unwrap()
    assert updated.status == JobStatus.CANCELLED


def test_invalid_spec_hash_rejected(db, tmp_path: Path):
    repo = SqliteRenderJobRepository(db)
    submit = SubmitRenderJobUseCase(repo)
    res = submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="",
        archive_path=tmp_path,
    )
    assert res.is_err()
    assert res.unwrap_err().code == ErrorCode.VALIDATION_FAILED


def test_get_job_not_found(db):
    repo = SqliteRenderJobRepository(db)
    get_job = GetRenderJobUseCase(repo)
    res = get_job.execute("non-existent-id")
    assert res.is_err()
    assert res.unwrap_err().code == ErrorCode.VALIDATION_FAILED


def test_worker_process_next_empty(db):
    repo = SqliteRenderJobRepository(db)
    renderer = _FakeRenderer(succeed=True)
    worker = RenderJobWorker(repo, renderer)
    res = worker.process_next()
    assert res.is_ok()
    assert res.unwrap() is None


def test_worker_cancelled_during_rendering(db, tmp_path: Path):
    repo = SqliteRenderJobRepository(db)
    clock = _FixedClock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    submit = SubmitRenderJobUseCase(repo, clock=clock)

    archive = tmp_path / "export"
    archive.mkdir()

    job, _ = submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="spec-to-cancel-mid-render",
        archive_path=archive,
    ).unwrap()

    class _CancellingRenderer:
        def render(self, archive: Path, *, destination: Path) -> Result[RenderedFilm, DomainError]:
            repo.cancel(job.id)
            manifest = destination.with_suffix(".manifest.json")
            frame = RenderedFrame("s1", destination, destination)
            return Ok(RenderedFilm(destination, manifest, (frame,), 10.0))

    worker = RenderJobWorker(repo, _CancellingRenderer(), clock=clock)
    res = worker.process_next()
    assert res.is_ok()
    assert res.unwrap().status == JobStatus.CANCELLED


def test_status_properties():
    assert JobStatus.PENDING.is_active is True
    assert JobStatus.RUNNING.is_active is True
    assert JobStatus.COMPLETED.is_active is False
    assert JobStatus.COMPLETED.is_terminal is True
    assert JobStatus.FAILED.is_terminal is True
    assert JobStatus.CANCELLED.is_terminal is True


def test_delete_for_family(db, tmp_path: Path):
    repo = SqliteRenderJobRepository(db)
    submit = SubmitRenderJobUseCase(repo)

    archive = tmp_path / "export"
    archive.mkdir()

    submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="spec-fam-1",
        archive_path=archive,
    )

    count = repo.delete_for_family(FamilyId("fam-1")).unwrap()
    assert count == 1
    assert len(repo.list_for_family(FamilyId("fam-1")).unwrap()) == 0
