"""Filesystem primitives that a cache can be built on.

Two operations, both about the same worry: a build writes its caches from
whichever worker finished the work first, and a half-written cache entry is
worse than no cache entry at all — every later build trusts it.
"""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_copy(source: Path, destination: Path) -> Path:
    """Copy through a temporary name in the destination's own directory.

    A plain copy that is interrupted - or raced by a second worker computing
    the same content address - leaves a truncated file under a name that says
    it is complete. `os.replace` on the same filesystem is atomic, so a cache
    entry either exists whole or does not exist.

    The temporary name carries the process and thread that wrote it, so two
    workers racing on the same key cannot collide on the temporary either.
    """
    ensure_dir(destination.parent)
    tmp = destination.with_name(f"{destination.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    shutil.copy2(source, tmp)
    tmp.replace(destination)  # atomic on one filesystem: whole, or absent
    return destination


def disk_usage(path: Path) -> int:
    """Bytes under a directory. Missing is zero, not an error."""
    if not path.is_dir():
        return 0
    return sum(entry.stat().st_size for entry in path.rglob("*") if entry.is_file())
