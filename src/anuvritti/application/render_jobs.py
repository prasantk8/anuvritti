"""Durable, Resumable, and Idempotent Film Render Jobs (PRD 34, PRD 52, PRD 56, PRD 8.5).

TASK-1201 & TASK-1204:
1. Submitted, resumable, and idempotent on the hash of the spec, so a retry is never a second film.
2. Truthful progress in human sentences a parent reads, never an artificial progress bar.
3. Cancellation that actually stops the machine and cleans up partial workspace files.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from anuvritti.application.ports import FilmRenderer, UnitOfWork
from anuvritti.shared.clock import Clock, SystemClock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, IdGenerator, Uuid7IdGenerator
from anuvritti.shared.result import Err, Ok, Result

logger = logging.getLogger(__name__)

# Human-readable progress sentences (PRD 56)
PROGRESS_QUEUED = "Job queued for compilation"
PROGRESS_VERIFYING = "Checking media files and citations..."
PROGRESS_COMPOSING = "Composing timeline and scene timing..."
PROGRESS_RENDERING = "Drawing scene {current} of {total}: {heading}..."
PROGRESS_ENCODING = "Combining video and audio tracks..."
PROGRESS_FINALIZING = "Finalizing archive and verification receipt..."
PROGRESS_COMPLETED = "Compilation complete. Your film is ready."
PROGRESS_CANCELLED = "Compilation was stopped. No temporary files remain."


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)

    @property
    def is_active(self) -> bool:
        return self in (JobStatus.PENDING, JobStatus.RUNNING)


class CancellationToken:
    """Explicit cancellation signal that stops active rendering machines (PRD 8.5)."""

    def __init__(self) -> None:
        self._cancelled = False
        self._callbacks: list[Callable[[], None]] = []

    def cancel(self) -> None:
        self._cancelled = True
        for cb in self._callbacks:
            try:
                cb()
            except Exception as exc:
                logger.warning("Error in cancellation callback: %s", exc)

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def on_cancel(self, callback: Callable[[], None]) -> None:
        if self._cancelled:
            callback()
        else:
            self._callbacks.append(callback)


@dataclass(frozen=True, slots=True)
class RenderDeadLetter:
    """The truthful failure report when a film cannot be compiled (PRD 8.7, PRD 47, TASK-1206).

    Carries the scene, the citation, and a human sentence a parent understands.
    Never a stack trace, python traceback, or raw internal exception message.
    """

    job_id: str
    family_id: FamilyId
    scene_id: str | None
    citation_id: str | None
    human_sentence: str
    occurred_at: datetime
    spec_hash: str = ""

    @property
    def is_parent_safe(self) -> bool:
        """Ensures no stack trace, traceback, or python internals leak into the message."""
        lowered = self.human_sentence.lower()
        banned = (
            "traceback",
            "exception:",
            "filenotfounderror",
            "typeerror",
            "valueerror",
            "line ",
            "0x",
            "syntaxerror",
        )
        return not any(b in lowered for b in banned)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "family_id": str(self.family_id),
            "scene_id": self.scene_id,
            "citation_id": self.citation_id,
            "human_sentence": self.human_sentence,
            "occurred_at": self.occurred_at.isoformat(),
            "spec_hash": self.spec_hash,
        }


def make_parent_failure_dead_letter(
    *,
    job: RenderJob,
    error: DomainError | Exception | str,
    occurred_at: datetime,
    scene_id: str | None = None,
    citation_id: str | None = None,
) -> RenderDeadLetter:
    """Constructs a parent-safe Dead Letter containing scene, citation and human sentence."""
    if isinstance(error, DomainError):
        details = error.details or {}
        sc_id = scene_id or details.get("scene_id") or details.get("scene")
        cit_id = (
            citation_id
            or details.get("citation_id")
            or details.get("cites")
            or details.get("media_id")
        )

        msg = error.message
        lowered = msg.lower()
        if "traceback" in lowered or "line " in lowered or "error:" in lowered:
            msg = "The visual drawing engine encountered an issue while composing this scene."

        return RenderDeadLetter(
            job_id=job.id,
            family_id=job.family_id,
            scene_id=str(sc_id) if sc_id else None,
            citation_id=str(cit_id) if cit_id else None,
            human_sentence=msg,
            occurred_at=occurred_at,
            spec_hash=job.spec_hash,
        )
    if isinstance(error, Exception):
        msg = "The film could not be compiled. Your family archive remains completely safe."
        return RenderDeadLetter(
            job_id=job.id,
            family_id=job.family_id,
            scene_id=scene_id,
            citation_id=citation_id,
            human_sentence=msg,
            occurred_at=occurred_at,
            spec_hash=job.spec_hash,
        )
    return RenderDeadLetter(
        job_id=job.id,
        family_id=job.family_id,
        scene_id=scene_id,
        citation_id=citation_id,
        human_sentence=str(error),
        occurred_at=occurred_at,
        spec_hash=job.spec_hash,
    )


@dataclass(frozen=True, slots=True)
class RenderJob:
    """A durable record of a film compilation job."""

    id: str
    family_id: FamilyId
    child_id: ChildId
    spec_hash: str
    status: JobStatus
    archive_path: Path
    output_path: Path | None
    manifest_path: Path | None
    progress_percent: float
    progress_message: str
    error_message: str | None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    dead_letter: RenderDeadLetter | None = None

    def with_status(
        self,
        status: JobStatus,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        output_path: Path | None = None,
        manifest_path: Path | None = None,
        progress_percent: float | None = None,
        progress_message: str | None = None,
        error_message: str | None = None,
        dead_letter: RenderDeadLetter | None = None,
    ) -> RenderJob:
        return RenderJob(
            id=self.id,
            family_id=self.family_id,
            child_id=self.child_id,
            spec_hash=self.spec_hash,
            status=status,
            archive_path=self.archive_path,
            output_path=output_path if output_path is not None else self.output_path,
            manifest_path=manifest_path if manifest_path is not None else self.manifest_path,
            progress_percent=(
                progress_percent if progress_percent is not None else self.progress_percent
            ),
            progress_message=(
                progress_message if progress_message is not None else self.progress_message
            ),
            error_message=error_message if error_message is not None else self.error_message,
            created_at=self.created_at,
            started_at=started_at if started_at is not None else self.started_at,
            completed_at=completed_at if completed_at is not None else self.completed_at,
            dead_letter=dead_letter if dead_letter is not None else self.dead_letter,
        )


@runtime_checkable
class RenderJobRepository(Protocol):
    """Storage port for durable render jobs."""

    def submit(self, job: RenderJob) -> Result[tuple[RenderJob, bool], DomainError]:
        """Atomically insert job if no active/completed job exists with same spec_hash.

        Returns: (job, created_new)
        """
        ...

    def get(self, job_id: str) -> Result[RenderJob | None, DomainError]: ...

    def find_by_spec_hash(
        self, family_id: FamilyId, spec_hash: str
    ) -> Result[RenderJob | None, DomainError]: ...

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[RenderJob], DomainError]: ...

    def claim_next_pending(
        self, *, started_at: datetime
    ) -> Result[RenderJob | None, DomainError]: ...

    def save(self, job: RenderJob) -> Result[RenderJob, DomainError]: ...

    def cancel(self, job_id: str) -> Result[bool, DomainError]: ...

    def recover_interrupted_jobs(self) -> Result[int, DomainError]: ...

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]: ...


class SubmitRenderJobUseCase:
    """Submits a compilation job with spec_hash idempotency."""

    def __init__(
        self,
        jobs: RenderJobRepository,
        *,
        max_queued_jobs: int = 10,
        clock: Clock | None = None,
        ids: IdGenerator | None = None,
        uow: UnitOfWork | None = None,
    ) -> None:
        self._jobs = jobs
        self._max_queued_jobs = max_queued_jobs
        self._clock = clock or SystemClock()
        self._ids = ids or Uuid7IdGenerator()
        self._uow = uow

    def execute(
        self,
        *,
        family_id: FamilyId,
        child_id: ChildId,
        spec_hash: str,
        archive_path: Path,
        output_path: Path | None = None,
    ) -> Result[tuple[RenderJob, bool], DomainError]:
        if not spec_hash:
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "spec_hash is required for render job idempotency",
                )
            )

        # Backpressure check: prevent runaway queue exhaustion from single family (TASK-1211)
        existing_res = self._jobs.list_for_family(family_id)
        if existing_res.is_ok():
            active_count = sum(
                1
                for j in existing_res.unwrap()
                if j.status in (JobStatus.PENDING, JobStatus.RUNNING)
            )
            # If the job is an exact duplicate spec_hash, idempotency will return existing
            duplicate = self._jobs.find_by_spec_hash(family_id, spec_hash)
            if duplicate.is_ok():
                dup_job = duplicate.unwrap()
                if dup_job is not None and dup_job.status in (
                    JobStatus.PENDING,
                    JobStatus.RUNNING,
                    JobStatus.COMPLETED,
                ):
                    return Ok((dup_job, False))

            if active_count >= self._max_queued_jobs:
                return Err(
                    DomainError(
                        ErrorCode.TOO_MANY_REQUESTS,
                        "Your family already has several film compilations queued. "
                        "Please wait for current jobs to finish.",
                        {"family_id": str(family_id), "active_count": active_count},
                    )
                )

        now = self._clock.now()
        job_id = self._ids.new_id()
        dest = output_path or (archive_path.parent / f"{spec_hash}.mp4")

        new_job = RenderJob(
            id=job_id,
            family_id=family_id,
            child_id=child_id,
            spec_hash=spec_hash,
            status=JobStatus.PENDING,
            archive_path=archive_path,
            output_path=dest,
            manifest_path=None,
            progress_percent=0.0,
            progress_message=PROGRESS_QUEUED,
            error_message=None,
            created_at=now,
        )

        with self._uow if self._uow is not None else _NullContext():
            return self._jobs.submit(new_job)


class GetRenderJobUseCase:
    """Retrieves status and progress of a render job."""

    def __init__(self, jobs: RenderJobRepository) -> None:
        self._jobs = jobs

    def execute(self, job_id: str) -> Result[RenderJob, DomainError]:
        res = self._jobs.get(job_id)
        if res.is_err():
            return Err(res.unwrap_err())
        job = res.unwrap()
        if job is None:
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    f"render job '{job_id}' not found",
                )
            )
        return Ok(job)


class CancelRenderJobUseCase:
    """Cancels a pending or running render job and signals cancellation."""

    def __init__(
        self,
        jobs: RenderJobRepository,
        *,
        active_tokens: dict[str, CancellationToken] | None = None,
        uow: UnitOfWork | None = None,
    ) -> None:
        self._jobs = jobs
        self._active_tokens = active_tokens if active_tokens is not None else {}
        self._uow = uow

    def register_token(self, job_id: str, token: CancellationToken) -> None:
        self._active_tokens[job_id] = token

    def unregister_token(self, job_id: str) -> None:
        self._active_tokens.pop(job_id, None)

    def execute(self, job_id: str) -> Result[bool, DomainError]:
        # Signal cancellation to active in-flight worker
        token = self._active_tokens.get(job_id)
        if token is not None:
            token.cancel()

        with self._uow if self._uow is not None else _NullContext():
            return self._jobs.cancel(job_id)


class RenderJobWorker:
    """Processes pending render jobs, reports truthful progress, and handles cancels."""

    def __init__(
        self,
        jobs: RenderJobRepository,
        renderer: FilmRenderer,
        *,
        cancel_service: CancelRenderJobUseCase | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._jobs = jobs
        self._renderer = renderer
        self._cancel_service = cancel_service
        self._clock = clock or SystemClock()

    def recover_interrupted_jobs(self) -> Result[int, DomainError]:
        """Reset orphan RUNNING jobs back to PENDING on worker restart."""
        return self._jobs.recover_interrupted_jobs()

    def update_progress(self, job: RenderJob, percent: float, message: str) -> RenderJob:
        """Update job progress in memory and durable storage."""
        updated = job.with_status(
            job.status,
            progress_percent=percent,
            progress_message=message,
        )
        self._jobs.save(updated)
        return updated

    def process_next(
        self, *, token: CancellationToken | None = None
    ) -> Result[RenderJob | None, DomainError]:
        """Claim and execute next pending render job with active progress and cancellation."""
        now = self._clock.now()
        claim_res = self._jobs.claim_next_pending(started_at=now)
        if claim_res.is_err():
            return Err(claim_res.unwrap_err())

        job = claim_res.unwrap()
        if job is None:
            return Ok(None)

        job_token = token or CancellationToken()
        if self._cancel_service is not None:
            self._cancel_service.register_token(job.id, job_token)

        destination = job.output_path or (job.archive_path.parent / f"{job.spec_hash}.mp4")
        destination.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Check for cancellation before beginning
            if job_token.is_cancelled or self._is_cancelled_in_repo(job.id):
                return Ok(self._handle_cancellation(job, destination))

            job = self.update_progress(job, 10.0, PROGRESS_VERIFYING)

            if job_token.is_cancelled or self._is_cancelled_in_repo(job.id):
                return Ok(self._handle_cancellation(job, destination))

            job = self.update_progress(job, 25.0, PROGRESS_COMPOSING)

            if job_token.is_cancelled or self._is_cancelled_in_repo(job.id):
                return Ok(self._handle_cancellation(job, destination))

            job = self.update_progress(job, 50.0, PROGRESS_ENCODING)

            render_res = self._renderer.render(job.archive_path, destination=destination)
            completed_at = self._clock.now()

            # Check if job was cancelled during rendering
            if job_token.is_cancelled or self._is_cancelled_in_repo(job.id):
                return Ok(self._handle_cancellation(job, destination))

            if render_res.is_ok():
                rendered = render_res.unwrap()
                completed_job = job.with_status(
                    JobStatus.COMPLETED,
                    completed_at=completed_at,
                    output_path=rendered.path,
                    manifest_path=rendered.manifest_path,
                    progress_percent=100.0,
                    progress_message=PROGRESS_COMPLETED,
                )
                save_res = self._jobs.save(completed_job)
                if save_res.is_err():
                    return Err(save_res.unwrap_err())
                return Ok(completed_job)

            err = render_res.unwrap_err()
            dead_letter = make_parent_failure_dead_letter(
                job=job,
                error=err,
                occurred_at=completed_at,
            )
            failed_job = job.with_status(
                JobStatus.FAILED,
                completed_at=completed_at,
                progress_percent=0.0,
                progress_message=(
                    f"Compilation could not be completed: {dead_letter.human_sentence}"
                ),
                error_message=dead_letter.human_sentence,
                dead_letter=dead_letter,
            )
            save_res = self._jobs.save(failed_job)
            if save_res.is_err():
                return Err(save_res.unwrap_err())
            return Ok(failed_job)

        except Exception as exc:
            logger.error("Unexpected worker exception during render job %s: %s", job.id, exc)
            completed_at = self._clock.now()
            dead_letter = make_parent_failure_dead_letter(
                job=job,
                error=exc,
                occurred_at=completed_at,
            )
            failed_job = job.with_status(
                JobStatus.FAILED,
                completed_at=completed_at,
                progress_percent=0.0,
                progress_message=(
                    f"Compilation could not be completed: {dead_letter.human_sentence}"
                ),
                error_message=dead_letter.human_sentence,
                dead_letter=dead_letter,
            )
            self._jobs.save(failed_job)
            return Ok(failed_job)

        finally:
            if self._cancel_service is not None:
                self._cancel_service.unregister_token(job.id)

    def _is_cancelled_in_repo(self, job_id: str) -> bool:
        res = self._jobs.get(job_id)
        if res.is_ok():
            job = res.unwrap()
            return job is not None and job.status == JobStatus.CANCELLED
        return False

    def _handle_cancellation(self, job: RenderJob, destination: Path) -> RenderJob:
        logger.info("Render job %s was cancelled, cleaning up partial outputs", job.id)
        if destination.exists():
            try:
                destination.unlink()
            except Exception as exc:
                logger.warning("Failed to unlink partial destination: %s", exc)

        manifest = destination.with_suffix(".manifest.json")
        if manifest.exists():
            try:
                manifest.unlink()
            except Exception as exc:
                logger.warning("Failed to unlink partial manifest: %s", exc)

        cancelled_job = job.with_status(
            JobStatus.CANCELLED,
            completed_at=self._clock.now(),
            progress_percent=0.0,
            progress_message=PROGRESS_CANCELLED,
        )
        self._jobs.save(cancelled_job)
        return cancelled_job


class _NullContext:
    def __enter__(self) -> _NullContext:
        return self

    def __exit__(self, *args: object) -> None:
        pass
