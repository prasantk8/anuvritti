"""The randomness port.

Secrets need entropy, and entropy is the one thing a test cannot assert against. So it
enters through a port, exactly as time and identity do: production draws from the OS CSPRNG,
tests inject a known sequence, and the *policy* — how many bytes, what alphabet, how long a
code lives — stays in the domain where it can be read and argued with.

Nothing here decides what a secret means. It only supplies bytes.
"""

from __future__ import annotations

import secrets
from typing import Protocol


class RandomSource(Protocol):
    """Cryptographically secure bytes. The only randomness the domain is allowed."""

    def token_bytes(self, count: int) -> bytes: ...


class SystemRandomSource:
    """Production source: the operating system CSPRNG, via `secrets`."""

    __slots__ = ()

    def token_bytes(self, count: int) -> bytes:
        if count < 1:
            raise ValueError(f"token_bytes needs a positive count, got {count}")
        return secrets.token_bytes(count)


class SequenceRandomSource:
    """Deterministic source for tests.

    Cycles a fixed byte pattern. Predictable on purpose — which is exactly why it must
    never be reachable from `build_container` without a test asking for it.
    """

    __slots__ = ("_n", "_seed")

    def __init__(self, seed: bytes = b"\x00\x01\x02\x03") -> None:
        if not seed:
            raise ValueError("SequenceRandomSource needs a non-empty seed")
        self._seed = seed
        self._n = 0

    def token_bytes(self, count: int) -> bytes:
        if count < 1:
            raise ValueError(f"token_bytes needs a positive count, got {count}")
        self._n += 1
        stretched = (bytes([self._n & 0xFF]) + self._seed) * (count // (len(self._seed) + 1) + 1)
        return stretched[:count]


__all__ = ["RandomSource", "SequenceRandomSource", "SystemRandomSource"]
