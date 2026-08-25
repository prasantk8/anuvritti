"""TASK-102 - the error catalog is a published contract (docs/contracts/errors.md)."""

from __future__ import annotations

import re
from pathlib import Path

from anuvritti.shared.errors import DomainError, ErrorCode

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "contracts" / "errors.md"


def test_every_code_in_the_contract_exists_in_the_enum():
    documented = set(re.findall(r"^\| `([A-Z_]+)` \|", CONTRACT.read_text(), re.MULTILINE))
    implemented = {c.value for c in ErrorCode}
    assert documented <= implemented, f"undocumented drift: {documented - implemented}"


def test_error_carries_code_message_and_details():
    err = DomainError(ErrorCode.SPARK_INVALID_TRANSITION, "cannot plan", {"from": "ARCHIVED"})
    assert err.code is ErrorCode.SPARK_INVALID_TRANSITION
    assert err.message == "cannot plan"
    assert err.details == {"from": "ARCHIVED"}


def test_details_default_to_empty_mapping():
    assert DomainError(ErrorCode.CONFLICT, "c").details == {}


def test_error_renders_to_the_wire_envelope():
    """docs/contracts/errors.md fixes this exact shape."""
    payload = DomainError(ErrorCode.PERMISSION_DENIED, "no").to_dict()
    assert payload == {"error": {"code": "PERMISSION_DENIED", "message": "no", "details": {}}}


def test_error_is_hashable_and_comparable():
    a = DomainError(ErrorCode.CONFLICT, "c")
    b = DomainError(ErrorCode.CONFLICT, "c")
    assert a == b
    assert len({a, b}) == 1
