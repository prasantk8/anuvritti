#!/usr/bin/env python3
"""Render Worker Daemon / CLI (TASK-1201, PRD 34, PRD 52).

Runs on the render machine:
1. Recovers any interrupted jobs from previous worker restarts.
2. Polls/claims pending render jobs from the durable job queue.
3. Invokes ChromiumFfmpegRenderer to compile the verified archive to mp4.
4. Updates job status to COMPLETED (or FAILED) with atomic progress reporting.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from anuvritti.adapters.film.render import ChromiumFfmpegRenderer
from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import SqliteRenderJobRepository
from anuvritti.application.render_jobs import RenderJobWorker
from anuvritti.config.settings import load_settings
from anuvritti.infrastructure.render_sandbox import RenderSandboxRunner
from anuvritti.shared.clock import SystemClock

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("render_worker")


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Worker for Durable Film Compilation")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Poll interval in seconds")
    parser.add_argument("--workspace", type=Path, default=Path("var/film/work"))
    parser.add_argument("--workers", type=int, default=1, help="Number of browser render workers")
    parser.add_argument(
        "--sandbox", action="store_true", help="Run render jobs in offline docker sandbox"
    )
    args = parser.parse_args()

    settings = load_settings()
    db_path = settings.db_path
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    connection = connect(str(db_path))
    migrate(connection)

    jobs_repo = SqliteRenderJobRepository(connection)
    if args.sandbox:
        sandbox_runner = RenderSandboxRunner()

        class _SandboxedRenderer:
            def render(self, archive: Path, *, destination: Path):
                return sandbox_runner.run_job(
                    archive_path=archive,
                    output_dir=destination.parent,
                    output_name=destination.name,
                )

        renderer = _SandboxedRenderer()  # type: ignore[assignment]
    else:
        renderer = ChromiumFfmpegRenderer(workspace=args.workspace, workers=args.workers)

    worker = RenderJobWorker(jobs=jobs_repo, renderer=renderer, clock=SystemClock())

    recovered = worker.recover_interrupted_jobs()
    if recovered.is_ok() and recovered.unwrap() > 0:
        logger.info("Recovered %d interrupted render jobs", recovered.unwrap())

    if args.once:
        res = worker.process_next()
        if res.is_err():
            logger.error("Job processing failed: %s", res.unwrap_err().message)
            return 1
        job = res.unwrap()
        if job is not None:
            logger.info("Processed job %s: status=%s", job.id, job.status)
        else:
            logger.info("No pending render jobs")
        return 0

    logger.info("Render worker started. Polling for jobs...")
    try:
        while True:
            res = worker.process_next()
            if res.is_ok():
                job = res.unwrap()
                if job is not None:
                    logger.info("Completed processing for job %s: status=%s", job.id, job.status)
                else:
                    time.sleep(args.poll_interval)
            else:
                logger.error("Error processing job: %s", res.unwrap_err().message)
                time.sleep(args.poll_interval)
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
        return 0


if __name__ == "__main__":
    sys.exit(main())
