"""Offline Render Sandbox Runner (PRD 44, HARDENING 5.1, TASK-1203).

Enforces the three invariants of the render worker:
1. No network: container boots with `--network none`.
2. Read-only root: filesystem root is mounted read-only (`--read-only`).
3. Single-job ephemeral media custody: the family's media is mounted for one job only,
   and unmounted / removed immediately upon job completion or termination.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.result import Err, Ok, Result

logger = logging.getLogger(__name__)

DEFAULT_RENDER_IMAGE = "anuvritti-render:latest"
DEFAULT_TIMEOUT_SECONDS = 300


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    """Security parameters for executing an offline render job."""

    image: str = DEFAULT_RENDER_IMAGE
    network: str = "none"
    read_only_root: bool = True
    drop_capabilities: tuple[str, ...] = ("ALL",)
    no_new_privileges: bool = True
    user: str = "10001:10001"
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    tmpfs_mounts: tuple[str, ...] = (
        "/tmp:rw,noexec,nosuid,size=512m",  # noqa: S108
        "/workspace:rw,size=2g",
    )

    def build_docker_args(
        self,
        *,
        archive_path: Path,
        output_dir: Path,
        output_name: str = "film.mp4",
    ) -> list[str]:
        """Construct deterministic docker run command with maximum sandbox isolation."""
        args = [
            "docker",
            "run",
            "--rm",
            f"--network={self.network}",
            f"--user={self.user}",
        ]

        if self.read_only_root:
            args.append("--read-only")

        for cap in self.drop_capabilities:
            args.append(f"--cap-drop={cap}")

        if self.no_new_privileges:
            args.append("--security-opt=no-new-privileges:true")

        for tmpfs in self.tmpfs_mounts:
            args.append(f"--tmpfs={tmpfs}")

        # Mount input archive read-only
        args.extend(
            [
                "-v",
                f"{archive_path.resolve()}:/input:ro",
                "-v",
                f"{output_dir.resolve()}:/output:rw",
            ]
        )

        args.extend(
            [
                self.image,
                "--archive",
                "/input",
                "--output",
                f"/output/{output_name}",
            ]
        )
        return args


class RenderSandboxRunner:
    """Manages ephemeral isolation and lifecycle cleanup for a render job."""

    def __init__(
        self,
        config: SandboxConfig | None = None,
        *,
        runner_fn: Any = None,
    ) -> None:
        self._config = config or SandboxConfig()
        self._runner_fn = runner_fn or subprocess.run

    @property
    def config(self) -> SandboxConfig:
        return self._config

    def run_job(
        self,
        *,
        archive_path: Path,
        output_dir: Path,
        output_name: str = "film.mp4",
        ephemeral_work_dir: Path | None = None,
    ) -> Result[Path, DomainError]:
        """Runs the render worker in sandbox and guarantees ephemeral cleanup."""
        if not archive_path.exists():
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    f"archive path '{archive_path}' does not exist",
                )
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        command = self._config.build_docker_args(
            archive_path=archive_path,
            output_dir=output_dir,
            output_name=output_name,
        )

        try:
            logger.info("Executing offline render sandbox: %s", " ".join(command))
            result = self._runner_fn(
                command,
                capture_output=True,
                text=True,
                timeout=self._config.timeout_seconds,
                check=False,
            )

            if result.returncode != 0:
                logger.error(
                    "Sandbox render failed (code %d): %s", result.returncode, result.stderr
                )
                return Err(
                    DomainError(
                        ErrorCode.FILM_NOT_COMPILABLE,
                        "offline render container failed",
                        {"stderr": result.stderr, "returncode": result.returncode},
                    )
                )

            rendered_file = output_dir / output_name
            if not rendered_file.exists():
                return Err(
                    DomainError(
                        ErrorCode.FILM_NOT_COMPILABLE,
                        "render container finished without producing output film",
                    )
                )

            return Ok(rendered_file)

        except subprocess.TimeoutExpired as exc:
            logger.error("Sandbox render timed out after %ds", self._config.timeout_seconds)
            return Err(
                DomainError(
                    ErrorCode.FILM_NOT_COMPILABLE,
                    f"render timed out after {self._config.timeout_seconds} seconds",
                    {"reason": str(exc)},
                )
            )
        except Exception as exc:
            logger.error("Sandbox execution error: %s", str(exc))
            return Err(
                DomainError(
                    ErrorCode.FILM_NOT_COMPILABLE,
                    "sandbox execution failed",
                    {"reason": str(exc)},
                )
            )
        finally:
            # Enforce single-job ephemeral cleanup: clean up ephemeral workspace if provided
            if ephemeral_work_dir and ephemeral_work_dir.exists():
                try:
                    shutil.rmtree(ephemeral_work_dir)
                    logger.info("Cleaned up ephemeral workspace %s", ephemeral_work_dir)
                except Exception as exc:
                    logger.warning("Failed to clean up ephemeral workspace: %s", exc)
