"""Where a build puts things.

filmkit reads no environment variable and knows no repository layout. It is
handed a `Workspace` and writes inside it - which is the difference between a
library and a program that happens to expose functions.

The reason is not tidiness. An environment variable named after a product is a
piece of that product's knowledge, and a package that reads one can only ever
serve that product. Two films compiled by the same code on the same machine
need two workspaces, and that is a caller's decision to make.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .files import ensure_dir


@dataclass(frozen=True, slots=True)
class Workspace:
    """The two directories a compile needs.

    `artifacts` is output: it belongs to one film and may be deleted whole.
    `cache` is content-addressed and shared across films - deleting it costs
    time and nothing else.
    """

    artifacts: Path
    cache: Path

    @classmethod
    def under(cls, root: Path) -> Workspace:
        """The obvious layout, for a caller that has no opinion."""
        return cls(artifacts=Path(root) / "artifacts", cache=Path(root) / "cache")

    def artifact(self, *parts: str) -> Path:
        """A directory under `artifacts`, created."""
        return ensure_dir(self.artifacts.joinpath(*parts))

    def store(self, name: str) -> Path:
        """A content-addressed cache store, created."""
        return ensure_dir(self.cache / name)
