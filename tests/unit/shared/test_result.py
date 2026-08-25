"""TASK-102 - Result/Either. ADR-0002: expected failures are values, not exceptions."""

from __future__ import annotations

import pytest

from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.result import Err, Ok, Result


def _boom(_: int) -> Result[int, DomainError]:
    return Err(DomainError(ErrorCode.VALIDATION_FAILED, "boom"))


class TestOk:
    def test_is_ok(self):
        assert Ok(1).is_ok() is True
        assert Ok(1).is_err() is False

    def test_unwrap_returns_value(self):
        assert Ok("v").unwrap() == "v"

    def test_unwrap_err_raises(self):
        with pytest.raises(ValueError, match="not an Err"):
            Ok(1).unwrap_err()

    def test_map_transforms(self):
        assert Ok(2).map(lambda x: x * 3).unwrap() == 6

    def test_and_then_chains(self):
        assert Ok(2).and_then(lambda x: Ok(x + 1)).unwrap() == 3

    def test_and_then_can_fail(self):
        assert Ok(2).and_then(_boom).is_err()

    def test_unwrap_or_ignores_default(self):
        assert Ok(2).unwrap_or(99) == 2


class TestErr:
    def test_is_err(self):
        err = Err(DomainError(ErrorCode.SPARK_NOT_FOUND, "nope"))
        assert err.is_err() is True
        assert err.is_ok() is False

    def test_unwrap_raises_with_the_error_message(self):
        err: Result[int, DomainError] = Err(DomainError(ErrorCode.SPARK_NOT_FOUND, "nope"))
        with pytest.raises(ValueError, match="nope"):
            err.unwrap()

    def test_unwrap_err_returns_error(self):
        e = DomainError(ErrorCode.SPARK_NOT_FOUND, "nope")
        assert Err(e).unwrap_err() is e

    def test_map_is_a_noop(self):
        err: Result[int, DomainError] = Err(DomainError(ErrorCode.CONFLICT, "c"))
        assert err.map(lambda x: x * 2).is_err()

    def test_and_then_short_circuits(self):
        calls: list[int] = []

        def never(x: int) -> Result[int, DomainError]:
            calls.append(x)
            return Ok(x)

        err: Result[int, DomainError] = Err(DomainError(ErrorCode.CONFLICT, "c"))
        assert err.and_then(never).is_err()
        assert calls == []

    def test_unwrap_or_returns_default(self):
        err: Result[int, DomainError] = Err(DomainError(ErrorCode.CONFLICT, "c"))
        assert err.unwrap_or(99) == 99


class TestResultIsImmutable:
    def test_ok_is_frozen(self):
        with pytest.raises(AttributeError):
            Ok(1).value = 2  # type: ignore[misc]

    def test_equality_by_value(self):
        assert Ok(1) == Ok(1)
        assert Ok(1) != Ok(2)
