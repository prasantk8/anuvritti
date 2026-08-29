"""TASK-1206: Failure that tells a family something true (PRD 8.7, PRD 47).

Verifies:
1. Dead letter carries the scene, the citation, and the truthful human sentence.
2. Never a stack trace, python traceback, or raw internal exception to a parent.
3. Archive remains untouched and family is told the exact reason for failure.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import SqliteRenderJobRepository
from anuvritti.application.ports import RenderedFilm
from anuvritti.application.render_jobs import (
    JobStatus,
    RenderDeadLetter,
    RenderJobWorker,
    SubmitRenderJobUseCase,
)
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId
from anuvritti.shared.result import Err, Result


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate(conn)
    conn.execute(
        "INSERT INTO family (id, name, created_at) VALUES (?, ?, ?)",
        ("fam-1", "Smiths", "2026-01-01T00:00:00Z"),
    )
    return conn


def test_dead_letter_carries_scene_citation_and_human_sentence(db, tmp_path: Path):
    """When a citation fails, the dead letter preserves the scene, citation, and human words."""
    repo = SqliteRenderJobRepository(db)
    submit = SubmitRenderJobUseCase(repo)

    archive = tmp_path / "archive"
    archive.mkdir()
    dest = tmp_path / "output" / "film.mp4"

    _job, _ = submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="spec-fail-1",
        archive_path=archive,
        output_path=dest,
    ).unwrap()

    class _FailingRenderer:
        def render(self, archive: Path, *, destination: Path) -> Result[RenderedFilm, DomainError]:
            return Err(
                DomainError(
                    ErrorCode.FILM_NOT_COMPILABLE,
                    "The audio recording for 'First Bike Ride' could not be found in your archive",
                    {"scene_id": "scene-bike-1", "cites": "aud-bike-rec"},
                )
            )

    worker = RenderJobWorker(repo, _FailingRenderer())
    result = worker.process_next()
    assert result.is_ok()
    failed_job = result.unwrap()

    assert failed_job.status == JobStatus.FAILED
    assert failed_job.dead_letter is not None

    dl = failed_job.dead_letter
    assert dl.scene_id == "scene-bike-1"
    assert dl.citation_id == "aud-bike-rec"
    assert (
        "The audio recording for 'First Bike Ride' could not be found in your archive"
        in dl.human_sentence
    )
    assert dl.is_parent_safe

    # Ensure parent message has no internal stack trace or raw code
    assert "traceback" not in failed_job.error_message.lower()
    assert "exception" not in failed_job.error_message.lower()
    assert "line " not in failed_job.error_message.lower()


def test_unexpected_crash_generates_parent_safe_dead_letter(db, tmp_path: Path):
    """When an unhandled python crash occurs, parent is given dignified words, not a traceback."""
    repo = SqliteRenderJobRepository(db)
    submit = SubmitRenderJobUseCase(repo)

    archive = tmp_path / "archive"
    archive.mkdir()
    dest = tmp_path / "output" / "film.mp4"

    _job, _ = submit.execute(
        family_id=FamilyId("fam-1"),
        child_id=ChildId("child-1"),
        spec_hash="spec-crash-1",
        archive_path=archive,
        output_path=dest,
    ).unwrap()

    class _CrashingRenderer:
        def render(self, archive: Path, *, destination: Path) -> Result[RenderedFilm, DomainError]:
            raise RuntimeError(
                "Segmentation fault / internal c-extension buffer overflow at 0xdeadbeef"
            )

    worker = RenderJobWorker(repo, _CrashingRenderer())
    result = worker.process_next()
    assert result.is_ok()
    failed_job = result.unwrap()

    assert failed_job.status == JobStatus.FAILED
    assert failed_job.dead_letter is not None

    dl = failed_job.dead_letter
    assert dl.is_parent_safe
    assert "Your family archive remains completely safe" in dl.human_sentence
    assert "0xdeadbeef" not in dl.human_sentence
    assert "segmentation fault" not in dl.human_sentence.lower()


def test_dead_letter_serialization():
    """Dead letter serializes to dictionary cleanly."""
    dl = RenderDeadLetter(
        job_id="job-123",
        family_id=FamilyId("fam-1"),
        scene_id="scene-1",
        citation_id="med-1",
        human_sentence="The photograph changed since the film was planned.",
        occurred_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
        spec_hash="spec-hash-123",
    )

    data = dl.to_dict()
    assert data["job_id"] == "job-123"
    assert data["family_id"] == "fam-1"
    assert data["scene_id"] == "scene-1"
    assert data["citation_id"] == "med-1"
    assert data["human_sentence"] == "The photograph changed since the film was planned."
    assert data["spec_hash"] == "spec-hash-123"
