"""The authentication boundary (HARDENING 5.1, TASK-511).

Before this existed, `family_id` and `actor_id` were request parameters. Anyone who could
reach the port could read anyone's archive by typing a different id. This module makes the
bearer token the only thing that decides whose data a request touches.

The rule is stated once, here, and applied by a single dependency, so there is no endpoint
where someone can forget it:

    An id that appears in a path, a query or a body is not an instruction.
    It is an assertion, and it must agree with the token or the request is refused.

That reading matters. The obvious alternative - "ignore the body's family_id, use the
token's" - is quietly worse: a client with a stale or wrong id would silently write into the
right family and never learn it had a bug. Disagreement is a 403, and the client finds out.
"""

from __future__ import annotations

from typing import Final

from fastapi import Request

from anuvritti.application.access import DeviceIdentity
from anuvritti.shared.errors import DomainError, ErrorCode

_BEARER: Final[str] = "bearer "

#: The one message. Missing, malformed, unknown and revoked all read identically, because
#: telling them apart tells a caller which tokens exist.
UNAUTHENTICATED: Final[DomainError] = DomainError(
    ErrorCode.UNAUTHENTICATED, "this device is not paired with a family"
)


class Refused(Exception):  # noqa: N818 - it is a carrier, not a failure of this module
    """A `DomainError` on its way to the boundary.

    FastAPI dependencies signal by raising, and the error envelope in
    docs/contracts/errors.md is a contract, so the exception carries a real `DomainError`
    rather than an `HTTPException` whose body would be a different shape.
    """

    def __init__(self, error: DomainError) -> None:
        super().__init__(error.message)
        self.error = error


def presented_token(request: Request) -> str | None:
    """Read `Authorization: Bearer <token>`.

    The scheme is compared case-insensitively because clients disagree about it, and the
    token is not: it is a secret, and a secret with a normalised case is a shorter secret.
    """
    header = request.headers.get("authorization")
    if not header or not header.lower().startswith(_BEARER):
        return None
    token = header[len(_BEARER) :].strip()
    return token or None


def same_family(identity: DeviceIdentity, *claimed: str | None) -> None:
    """Refuse any request that names a family other than the token's.

    Raises rather than returns because there is no sensible partial outcome: if the caller
    and the token disagree about whose child this is, nothing about the request is safe.
    """
    for family_id in claimed:
        if not identity.owns(family_id):
            raise Refused(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    "this device is paired with a different family",
                )
            )


def same_member(identity: DeviceIdentity, *claimed: str | None) -> None:
    """Refuse a request that acts as someone other than the member this device belongs to.

    A device is one person's. Co-parents get their own device and their own token, which is
    TASK-902's promise made cheap: it is already the only shape this boundary allows.
    """
    for member_id in claimed:
        if member_id is not None and member_id != str(identity.member_id):
            raise Refused(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    "this device acts for one member only",
                )
            )


__all__ = [
    "UNAUTHENTICATED",
    "Refused",
    "presented_token",
    "same_family",
    "same_member",
]
