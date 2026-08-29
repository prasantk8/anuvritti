"""Typed identifiers and id generation.

A `SparkId` and a `MomentId` are never interchangeable, even though both wrap a string.
The type system, not a code review, prevents passing the wrong one.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class _Identifier:
    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValueError(f"{type(self).__name__} cannot be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class FamilyId(_Identifier): ...


@dataclass(frozen=True, slots=True)
class MemberId(_Identifier): ...


@dataclass(frozen=True, slots=True)
class ChildId(_Identifier): ...


@dataclass(frozen=True, slots=True)
class SparkId(_Identifier): ...


@dataclass(frozen=True, slots=True)
class MomentId(_Identifier): ...


@dataclass(frozen=True, slots=True)
class MediaId(_Identifier): ...


@dataclass(frozen=True, slots=True)
class LittleThingId(_Identifier): ...


@dataclass(frozen=True, slots=True)
class RightNowId(_Identifier): ...


@dataclass(frozen=True, slots=True)
class FutureMessageId(_Identifier): ...


@dataclass(frozen=True, slots=True)
class EventId(_Identifier): ...


@dataclass(frozen=True, slots=True)
class DeviceId(_Identifier): ...


class IdGenerator(Protocol):
    """Port. Kept behind an interface so tests can be deterministic."""

    def new_id(self) -> str: ...


class Uuid7IdGenerator:
    """UUIDv7-style: 48-bit millisecond prefix, so ids sort chronologically.

    A family archive read in id order is read in the order life happened.
    """

    __slots__ = ("_counter", "_last_ms")

    def __init__(self) -> None:
        self._last_ms = 0
        self._counter = 0

    def new_id(self) -> str:
        now_ms = time.time_ns() // 1_000_000
        if now_ms == self._last_ms:
            self._counter += 1
        else:
            self._last_ms = now_ms
            self._counter = 0
        # 48-bit time | 16-bit monotonic counter | 64 bits of randomness
        rand = int.from_bytes(os.urandom(8), "big")
        raw = (now_ms << 80) | ((self._counter & 0xFFFF) << 64) | rand
        return str(uuid.UUID(int=raw & ((1 << 128) - 1)))


class SequentialIdGenerator:
    """Deterministic generator for tests. Also chronologically ordered."""

    __slots__ = ("_n", "_prefix")

    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"{self._prefix}-{self._n:06d}"
