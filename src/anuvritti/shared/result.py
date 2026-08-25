"""Result / Either.

ADR-0002: expected failures are values, not exceptions. Every domain and application
operation that can fail says so in its return type.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never


@dataclass(frozen=True, slots=True)
class Ok[T]:
    """A successful outcome carrying its value."""

    value: T

    def is_ok(self) -> bool:
        return True

    def is_err(self) -> bool:
        return False

    def unwrap(self) -> T:
        return self.value

    def unwrap_or(self, default: T) -> T:  # noqa: ARG002 - interface conformance
        return self.value

    def unwrap_err(self) -> Never:
        raise ValueError(f"called unwrap_err on an Ok, not an Err: {self.value!r}")

    def map[U](self, fn: Callable[[T], U]) -> Ok[U]:
        return Ok(fn(self.value))

    def and_then[U, E](self, fn: Callable[[T], Result[U, E]]) -> Result[U, E]:
        return fn(self.value)


@dataclass(frozen=True, slots=True)
class Err[E]:
    """A failed outcome carrying the reason."""

    error: E

    def is_ok(self) -> bool:
        return False

    def is_err(self) -> bool:
        return True

    def unwrap(self) -> Never:
        raise ValueError(f"called unwrap on an Err: {self.error}")

    def unwrap_or[T](self, default: T) -> T:
        return default

    def unwrap_err(self) -> E:
        return self.error

    def map[T, U](self, fn: Callable[[T], U]) -> Err[E]:  # noqa: ARG002 - short-circuits
        return self

    def and_then[T, U](self, fn: Callable[[T], Result[U, E]]) -> Err[E]:  # noqa: ARG002
        return self


type Result[T, E] = Ok[T] | Err[E]
