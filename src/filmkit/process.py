"""Running external tools, and refusing to lose what they said.

Everything expensive in a film compile is a subprocess - ffmpeg, ffprobe, a
speech synthesiser - and every one of them gets a timeout, captured streams, an
exit code and, on request, a log file. A failed command must never become
successful-looking output; that is the one way a compiler can lie about its own
work.

`Runner` is a protocol rather than a function reference because filmkit is
handed the thing that runs commands. A caller with its own subprocess
discipline - its own logging, its own sandbox, its own refusal to shell out at
all - passes that in, and every ffmpeg call in this package goes through it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .files import ensure_dir

TIMED_OUT = 124


@dataclass(frozen=True, slots=True)
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_sec: float
    log_path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandError(RuntimeError):
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-20:]
        super().__init__(
            f"command failed ({result.returncode}): {' '.join(result.argv)}\n"
            + "\n".join(tail)
            + (f"\nlog: {result.log_path}" if result.log_path else "")
        )


class Runner(Protocol):
    def __call__(
        self,
        argv: list[str],
        *,
        cwd: Path | None = ...,
        env: dict[str, str] | None = ...,
        timeout: float = ...,
        check: bool = ...,
        log_name: str | None = ...,
    ) -> CommandResult: ...


def run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 600.0,
    check: bool = True,
    log_name: str | None = None,
    log_dir: Path | None = None,
) -> CommandResult:
    """Run one command. A timeout is a result, not an exception to swallow.

    A command that runs out of time still produced whatever it managed to say
    before it did, and that partial output is usually the explanation. So the
    streams are kept and the exit code becomes 124 - the shell's own convention
    - rather than the whole result being replaced by a traceback.
    """
    started = time.time()
    try:
        proc = subprocess.run(  # noqa: S603 - argv is built by this package, never a shell string
            argv,
            cwd=str(cwd) if cwd else None,
            env={**os.environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        captured = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        stderr = f"{captured}\ntimed out after {timeout}s"
        code = TIMED_OUT

    log_path = None
    if log_name and log_dir is not None:
        log_path = ensure_dir(log_dir) / f"{log_name}.log"
        log_path.write_text(
            f"$ {' '.join(argv)}\n(exit {code})\n\n"
            f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}\n"
        )

    result = CommandResult(argv, code, stdout, stderr, time.time() - started, log_path)
    if check and not result.ok:
        raise CommandError(result)
    return result


def which(binary: str) -> str | None:
    return shutil.which(binary)


def tool_version(binary: str, *args: str, runner: Runner | None = None) -> str | None:
    """Best-effort version string, for a manifest's tool inventory.

    Best-effort on purpose: a missing tool is a fact worth recording as `null`,
    not a reason to fail a build that never needed it.
    """
    if not which(binary):
        return None
    call = runner or run
    try:
        result = call([binary, *(args or ("--version",))], timeout=30, check=False)
    except OSError:
        return None
    text = (result.stdout or result.stderr).strip()
    return text.splitlines()[0] if text else None
