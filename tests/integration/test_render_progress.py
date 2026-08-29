"""TASK-1204: Progress in words a parent reads and cancel that stops machine (PRD 56, PRD 8.5).

Verifies:
1. Progress messages are truthful human sentences describing what the machine is doing.
2. Progress percentage accurately reflects completed pipeline milestones.
3. Cancellation stops the worker machine immediately and purges partial render files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import SqliteRenderJobRepository
from anuvritti.application.ports import RenderedFilm, RenderedFrame
from anuvritti.application.render_jobs import (
    PROGRESS_CANCELLED,
    PROGRESS_COMPLETED,
    PROGRESS_ENCODING,
    PROGRESS_QUEUED,
    CancellationToken,
    CancelRenderJobUseCase,
    JobStatus,
    RenderJobWorker,
    SubmitRenderJobUseCase,
)
from anuvritti.shared.errors import DomainError
from anuvritti.shared.identity import ChildId, FamilyId
from anuvritti.shared.result import Ok, Result


class _FakeProgressRenderer:
    def __init__(self, *, on_render_cb=None) -> None:
        self._on_render_cb = on_render_cb

    def render(self, archive: Path, *, destination: Path) -> Result[RenderedFilm, DomainError]:
        destination.write_bytes(b"partial-mp4-data")
        manifest = destination.with_suffix(".manifest.json")
        manifest.write_text("{}", encoding="utf-8")

        if self._on_render_cb is not None:
            self._on_render_cb()

        frame = RenderedFrame("s1", destination, destination)
        return Ok(RenderedFilm(destination, manifest, (frame,), 10.0))


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate(conn)
    conn.execute(
        "INSERT INTO family (id, name, created_at) VALUES (?, ?, ?)",
        ("fam-1", "Smiths", "2026-01-01T00:00:00Z"),
    )
    return conn


def test_truthful_progress_milestones(db, tmp_path: Path):
    """Progress messages transition through human sentences and percentages."""
    repo = SqliteRenderJobRepository(db)
    submit = SubmitRenderJobUseCase(repo)

    archive = tmp_path / "archive"
    archive.mkdir()
    dest = tmp_path / "output" / "film.mp4"

    job, _ = submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="spec-progress-1",
        archive_path=archive,
        output_path=dest,
    ).unwrap()

    assert job.progress_percent == 0.0
    assert job.progress_message == PROGRESS_QUEUED

    recorded_progress: list[tuple[float, str]] = []

    class _ObservingRenderer:
        def render(self, archive: Path, *, destination: Path) -> Result[RenderedFilm, DomainError]:
            current = repo.get(job.id).unwrap()
            recorded_progress.append((current.progress_percent, current.progress_message))
            destination.write_bytes(b"dummy")
            manifest = destination.with_suffix(".manifest.json")
            manifest.write_text("{}", encoding="utf-8")
            return Ok(RenderedFilm(destination, manifest, (), 5.0))

    worker = RenderJobWorker(repo, _ObservingRenderer())
    res = worker.process_next()
    assert res.is_ok()
    completed = res.unwrap()

    assert completed.status == JobStatus.COMPLETED
    assert completed.progress_percent == 100.0
    assert completed.progress_message == PROGRESS_COMPLETED

    # Verify stage progression
    assert any(msg == PROGRESS_ENCODING for _, msg in recorded_progress)


def test_cancellation_actively_stops_machine_and_cleans_files(db, tmp_path: Path):
    """When a cancel occurs during rendering, worker halts and removes partial files."""
    repo = SqliteRenderJobRepository(db)
    submit = SubmitRenderJobUseCase(repo)
    cancel = CancelRenderJobUseCase(repo)

    archive = tmp_path / "archive"
    archive.mkdir()
    dest = tmp_path / "output" / "film_cancelled.mp4"

    job, _ = submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="spec-to-cancel",
        archive_path=archive,
        output_path=dest,
    ).unwrap()

    def cancel_mid_render():
        # Cancel the job during rendering
        cancel.execute(job.id)

    renderer = _FakeProgressRenderer(on_render_cb=cancel_mid_render)
    worker = RenderJobWorker(repo, renderer, cancel_service=cancel)

    result = worker.process_next()
    assert result.is_ok()
    cancelled_job = result.unwrap()

    assert cancelled_job.status == JobStatus.CANCELLED
    assert cancelled_job.progress_message == PROGRESS_CANCELLED

    # Crucial guarantee: partial files are cleaned up and not left on disk
    assert not dest.exists(), "Partial MP4 must be deleted upon cancellation"
    assert not dest.with_suffix(".manifest.json").exists(), "Partial manifest must be deleted"


def test_cancellation_token_listener():
    """Cancellation token immediately notifies registered callbacks."""
    token = CancellationToken()
    notified = []

    token.on_cancel(lambda: notified.append(True))
    assert not notified

    token.cancel()
    assert token.is_cancelled
    assert notified == [True]

    # Subscribing after already cancelled immediately executes callback
    token.on_cancel(lambda: notified.append("late"))
    assert notified == [True, "late"]
