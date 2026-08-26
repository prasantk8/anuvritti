"""What a manifest is made of.

A film compiled by machine is only worth as much as the account it can give of
itself. This module does not decide what a manifest says - that is the host
application's, because only it knows what its film claims. It supplies the
parts that are the same for every such account: which tools were present and at
what version, what commit the inputs were at, what the outputs hash to, and how
much disk it all took.

Every one of these is best-effort in the same direction. A missing tool is
recorded as `null`, because "we do not know" is a true statement and a crashed
build is not a better one. What is never best-effort is an output digest: if a
file is claimed as an output, it is hashed, and a file that is not there is
simply not claimed.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .files import disk_usage, ensure_dir
from .hashing import sha256_file
from .process import Runner, run, tool_version

Tool = tuple[str, tuple[str, ...]]


def tool_versions(tools: Sequence[Tool], *, runner: Runner | None = None) -> dict[str, str | None]:
    """Version strings for external binaries. Absent is `None`, not an error."""
    return {name: tool_version(argv[0], *argv[1:], runner=runner) for name, argv in tools}


def distribution_versions(names: Sequence[str]) -> dict[str, str | None]:
    """Installed package versions, by distribution name.

    Distribution metadata rather than a `__version__` attribute, because the
    metadata is what a lockfile pins and several packages expose no attribute
    at all.
    """
    from importlib.metadata import PackageNotFoundError, version

    found: dict[str, str | None] = {}
    for name in names:
        try:
            found[name.lower()] = version(name)
        except PackageNotFoundError:
            found[name.lower()] = None
    return found


def browser_version() -> str | None:
    """Which Chromium drew the frames.

    Worth recording even though it is chosen for us: a frame drawn by a
    different browser is a different frame, and this is the only place that
    fact is written down.
    """
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            found: str = browser.version
            browser.close()
            return found
    except Exception:
        return None


def git_commit(repo: Path, *, runner: Runner | None = None) -> str | None:
    """The commit an input repository was at, or `None` if it is not one."""
    if not (repo / ".git").exists():
        return None
    call = runner or run
    result = call(["git", "-C", str(repo), "rev-parse", "HEAD"], timeout=30, check=False)
    return result.stdout.strip() or None


def output_digests(outputs: dict[str, Path]) -> dict[str, dict[str, Any]]:
    """Size and hash of every output that actually exists."""
    return {
        name: {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for name, path in outputs.items()
        if path.is_file()
    }


def disk(*paths: Path) -> dict[str, int]:
    """Bytes under each named path, keyed by its final component."""
    return {path.name: disk_usage(path) for path in paths}


def stamp() -> str:
    """The one timestamp a manifest is allowed: when it was written."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write(manifest: dict[str, Any], path: Path) -> Path:
    ensure_dir(path.parent)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return path
