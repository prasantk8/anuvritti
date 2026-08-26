"""How a compile says what it is doing, without deciding how it looks.

A library that prints has taken a decision that belongs to the program running
it. So filmkit reports through one method - `cache(verb, what)` - and anything
with that method satisfies the protocol structurally. A host application's own
console does, without inheriting from anything here.

`cache` is the only channel because it is the only thing filmkit knows that the
caller does not: whether a piece of work was done or reused. Everything else -
phases, totals, colour, whether to print at all - is the caller's.
"""

from __future__ import annotations

from typing import Protocol

HIT = "CACHE HIT"
MISS = "RENDER"


class Reporter(Protocol):
    def cache(self, verb: str, what: str) -> None: ...


class Silent:
    """Says nothing. The default, so a caller must opt in to output."""

    def cache(self, verb: str, what: str) -> None:  # noqa: ARG002 - the point is to ignore them
        return None


class Recorder:
    """Keeps what would have been said, in the order it was said.

    Parallel work produces interleaved progress lines from several encoders at
    once, which is worse than no progress lines at all. Each worker reports
    into its own recorder and the results are replayed in the caller's order
    once the pool drains - so concurrency changes the speed and not the story.
    """

    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def cache(self, verb: str, what: str) -> None:
        self.lines.append((verb, what))

    def replay(self, reporter: Reporter) -> None:
        for verb, what in self.lines:
            reporter.cache(verb, what)
