"""The content-addressed stores, and the discipline that keeps them bounded.

Three stores, each keyed by content rather than by name:

    tts       narration audio, keyed by text + voice + rate + pitch + synth
    frames    still states, keyed by markup + geometry + theme + renderer
    scenes    per-scene video, keyed by frames + audio + encoder flags

They exist because a rebuild after a one-word edit should cost seconds. They
are safe to keep because nothing in a key is a timestamp.

"Bounded" means two things. Every entry records when it was last *used*, not
just when it was written - a hit touches the file - so "nothing has asked for
this in a month" is a fact rather than a guess. And pruning is by that number,
so the answer to "what is this twenty gigabytes" is one call rather than an
archaeology session.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SECONDS_PER_DAY = 86400.0

STORES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("tts", "narration audio", ("*.mp3", "*.json")),
    ("frames", "rendered still states", ("*.png",)),
    ("scenes", "per-scene video and transcodes", ("*.mp4", "*.webm")),
)


def touch(path: Path) -> None:
    """Record a cache hit.

    Failure here must never fail a compile. The worst case is that a live entry
    looks stale to a later prune, which costs the time to render it again - and
    that is strictly better than a build that dies because it could not write
    an access time.
    """
    with contextlib.suppress(OSError):
        os.utime(path, None)


@dataclass(frozen=True, slots=True)
class StoreReport:
    name: str
    description: str
    path: Path
    entries: int
    bytes: int
    oldest_use_days: float

    def to_json(self) -> dict[str, Any]:
        return {
            "store": self.name,
            "entries": self.entries,
            "bytes": self.bytes,
            "oldest_use_days": round(self.oldest_use_days, 2),
        }


def survey(root: Path) -> list[StoreReport]:
    """What each store holds, and how long since anything wanted the oldest."""
    now = time.time()
    reports = []
    for name, description, patterns in STORES:
        directory = root / name
        files = (
            [f for pattern in patterns for f in directory.glob(pattern)]
            if directory.is_dir()
            else []
        )
        total = sum(f.stat().st_size for f in files)
        oldest = min((now - f.stat().st_mtime for f in files), default=0.0)
        reports.append(
            StoreReport(name, description, directory, len(files), total, oldest / SECONDS_PER_DAY)
        )
    return reports


def prune(older_than_days: float, root: Path) -> tuple[int, int]:
    """Delete entries nothing has used in that long. Returns (files, bytes).

    Never a correctness risk, only a time one: a pruned entry is regenerated
    the next time it is asked for, byte for byte, because the key is the
    content.
    """
    cutoff = time.time() - older_than_days * SECONDS_PER_DAY
    removed = freed = 0
    for name, _, patterns in STORES:
        directory = root / name
        if not directory.is_dir():
            continue
        for pattern in patterns:
            for entry in directory.glob(pattern):
                if entry.stat().st_mtime < cutoff:
                    freed += entry.stat().st_size
                    entry.unlink()
                    removed += 1
    return removed, freed


def clear(root: Path) -> tuple[int, int]:
    """Remove every store. The next compile is a cold one, and that is all."""
    removed = freed = 0
    for report in survey(root):
        removed += report.entries
        freed += report.bytes
        if report.path.is_dir():
            shutil.rmtree(report.path)
    return removed, freed


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
