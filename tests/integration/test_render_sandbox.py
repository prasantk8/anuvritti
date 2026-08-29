"""TASK-1203: Offline Sandboxed Render Worker (PRD 44, HARDENING 5.1).

Verifies the three invariants of the render worker sandbox:
1. No network: executes with `--network none`.
2. Read-only root: filesystem root is mounted `--read-only` with ephemeral tmpfs.
3. Ephemeral custody: media is mounted for one job only, then cleanly removed upon exit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from anuvritti.infrastructure.render_sandbox import (
    RenderSandboxRunner,
    SandboxConfig,
)
from anuvritti.shared.errors import ErrorCode


def test_dockerfile_security_directives():
    """The render Dockerfile must declare unprivileged user, offline assets, and non-root."""
    dockerfile = Path("docker/render.Dockerfile")
    assert dockerfile.exists(), "docker/render.Dockerfile must exist"
    content = dockerfile.read_text(encoding="utf-8")

    # Non-root user with UID 10001
    assert "useradd --system --uid 10001" in content
    assert "USER anuvritti:anuvritti" in content

    # Bundles browser binaries offline
    assert "PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers" in content
    assert "playwright install --with-deps chromium" in content

    # Workdir and entrypoint
    assert "WORKDIR /workspace" in content
    assert 'ENTRYPOINT ["python3", "scripts/render_worker.py"]' in content


def test_sandbox_docker_command_isolation(tmp_path: Path):
    """The sandbox runner must generate flags enforcing no network and read-only root."""
    config = SandboxConfig(
        image="test-render:v1",
        network="none",
        read_only_root=True,
        drop_capabilities=("ALL",),
        no_new_privileges=True,
        user="10001:10001",
    )

    archive = tmp_path / "job_archive"
    archive.mkdir()
    out_dir = tmp_path / "job_output"
    out_dir.mkdir()

    args = config.build_docker_args(
        archive_path=archive,
        output_dir=out_dir,
        output_name="my_film.mp4",
    )

    assert "docker" in args
    assert "run" in args
    assert "--rm" in args
    assert "--network=none" in args
    assert "--read-only" in args
    assert "--cap-drop=ALL" in args
    assert "--security-opt=no-new-privileges:true" in args
    assert "--user=10001:10001" in args

    # Input archive is mounted strictly read-only (:ro)
    assert f"{archive.resolve()}:/input:ro" in args
    assert f"{out_dir.resolve()}:/output:rw" in args

    # Tmpfs for mutable runtime operations
    assert "--tmpfs=/tmp:rw,noexec,nosuid,size=512m" in args
    assert "--tmpfs=/workspace:rw,size=2g" in args


def test_sandbox_runner_success(tmp_path: Path):
    """Successful sandbox execution creates output artifact."""
    archive = tmp_path / "archive"
    archive.mkdir()
    out_dir = tmp_path / "output"
    out_dir.mkdir()
    work_dir = tmp_path / "ephemeral_work"
    work_dir.mkdir()
    (work_dir / "temp.raw").write_bytes(b"temp-data")

    output_film = out_dir / "film.mp4"

    def mock_run(command, **kwargs):
        # Simulate container writing output
        output_film.write_bytes(b"dummy-mp4-stream")
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "rendered successfully"
        mock.stderr = ""
        return mock

    runner = RenderSandboxRunner(runner_fn=mock_run)
    res = runner.run_job(
        archive_path=archive,
        output_dir=out_dir,
        ephemeral_work_dir=work_dir,
    )

    assert res.is_ok()
    assert res.unwrap() == output_film
    assert output_film.exists()

    # Ephemeral work directory must be destroyed after the job
    assert not work_dir.exists(), "Ephemeral workspace must be deleted immediately after job"


def test_sandbox_runner_failure_cleans_up(tmp_path: Path):
    """When container fails, error is reported and ephemeral workspace is still cleaned up."""
    archive = tmp_path / "archive"
    archive.mkdir()
    out_dir = tmp_path / "output"
    work_dir = tmp_path / "ephemeral_work"
    work_dir.mkdir()
    (work_dir / "temp.raw").write_bytes(b"temp-data")

    def mock_fail(command, **kwargs):
        mock = MagicMock()
        mock.returncode = 137
        mock.stdout = ""
        mock.stderr = "Out of memory / killed"
        return mock

    runner = RenderSandboxRunner(runner_fn=mock_fail)
    res = runner.run_job(
        archive_path=archive,
        output_dir=out_dir,
        ephemeral_work_dir=work_dir,
    )

    assert res.is_err()
    assert res.unwrap_err().code == ErrorCode.FILM_NOT_COMPILABLE
    assert "offline render container failed" in res.unwrap_err().message

    # Ephemeral work directory must still be destroyed
    assert not work_dir.exists(), "Ephemeral workspace must be deleted even on job failure"


def test_sandbox_runner_timeout_handling(tmp_path: Path):
    """Timeout aborts job, returns error, and guarantees ephemeral cleanup."""
    archive = tmp_path / "archive"
    archive.mkdir()
    out_dir = tmp_path / "output"
    work_dir = tmp_path / "ephemeral_work"
    work_dir.mkdir()

    def mock_timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(cmd=command, timeout=10)

    config = SandboxConfig(timeout_seconds=10)
    runner = RenderSandboxRunner(config=config, runner_fn=mock_timeout)
    res = runner.run_job(
        archive_path=archive,
        output_dir=out_dir,
        ephemeral_work_dir=work_dir,
    )

    assert res.is_err()
    assert "timed out" in res.unwrap_err().message
    assert not work_dir.exists()


def test_sandbox_nonexistent_archive():
    """Non-existent archive is caught before launching docker."""
    runner = RenderSandboxRunner()
    res = runner.run_job(
        archive_path=Path("/nonexistent/archive/path"),
        output_dir=Path("/output"),
    )
    assert res.is_err()
    assert res.unwrap_err().code == ErrorCode.VALIDATION_FAILED


def test_sandbox_runner_missing_output_file(tmp_path: Path):
    """When container returns 0 but output file does not exist, reports failure."""
    archive = tmp_path / "archive"
    archive.mkdir()
    out_dir = tmp_path / "output"
    out_dir.mkdir()

    def mock_run_no_file(command, **kwargs):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = ""
        mock.stderr = ""
        return mock

    runner = RenderSandboxRunner(runner_fn=mock_run_no_file)
    res = runner.run_job(archive_path=archive, output_dir=out_dir)
    assert res.is_err()
    assert "without producing output" in res.unwrap_err().message


def test_sandbox_runner_generic_exception(tmp_path: Path):
    """When runner raises an unexpected error, returns error and cleans up."""
    archive = tmp_path / "archive"
    archive.mkdir()
    out_dir = tmp_path / "output"

    def mock_crash(command, **kwargs):
        raise OSError("Docker socket unavailable")

    runner = RenderSandboxRunner(runner_fn=mock_crash)
    res = runner.run_job(archive_path=archive, output_dir=out_dir)
    assert res.is_err()
    assert "sandbox execution failed" in res.unwrap_err().message
