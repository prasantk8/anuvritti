"""Device pairing (HARDENING 5.1).

V0 had no authentication at all: `family_id` and `actor_id` arrived as request parameters,
so any caller could name any family and read a stranger's archive. This module closes that
for the case the product actually has — one family, several of their own devices — without
taking on accounts, passwords or multi-tenancy, which are Phase 9.

The shape is deliberately small:

* A paired **device** holds a long, opaque bearer token. The token *is* the family and the
  member; nothing a request body says can widen it.
* A device is paired by transcribing a short **pairing code** shown on an already-paired
  device. The code is single-use, short-lived and attempt-limited.

Three decisions worth stating, because each one is a place this normally goes wrong:

**Only fingerprints are stored.** Neither the token nor the code is ever written to the
database in a form that could be replayed from a stolen backup. `sha256` — not argon2 — is
correct here, and the reason is not laziness: these are 256-bit and 40-bit *random* secrets,
not passwords. There is no dictionary to run and no human-chosen pattern to exploit, so a
slow KDF buys nothing while adding a per-request cost that is itself a denial-of-service
lever. The 40-bit code is protected by five attempts and ten minutes, not by hash cost.

**Failure is one error, never four.** Wrong code, expired code, already-claimed code and
too-many-attempts all return `PAIRING_FAILED`. Distinguishing them tells an attacker which
codes exist, which is the entire information they need.

**Comparison is constant-time.** `hmac.compare_digest`, everywhere a secret is checked.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Final, Self

from anuvritti.domain.events import DomainEvent
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import DeviceId, FamilyId, MemberId
from anuvritti.shared.randomness import RandomSource
from anuvritti.shared.result import Err, Ok, Result

#: 32 bytes of CSPRNG output. 256 bits is not a round number chosen for looks: it puts the
#: token permanently outside brute force even if the fingerprint table leaks.
TOKEN_BYTES: Final[int] = 32

#: Marks the string as ours wherever it lands — a log line, a crash report, a secret scanner.
TOKEN_PREFIX: Final[str] = "anv_"  # noqa: S105 - a prefix, not a secret; that is its job

#: 5 bytes -> 8 Crockford characters -> 40 bits. Short enough to read across a room.
CODE_BYTES: Final[int] = 5
CODE_LENGTH: Final[int] = 8

#: Crockford base32: no I, L, O or U. The first three are unreadable next to 1 and 0; the
#: fourth is omitted so a random code cannot spell something a parent has to read aloud.
_CROCKFORD: Final[str] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

#: I/L read as 1 and O reads as 0 in almost every typeface. Accept the mistake silently.
_TRANSCRIPTION_FIXES: Final[dict[str, str]] = {"I": "1", "L": "1", "O": "0", "U": "V"}

#: Long enough to walk to the other phone. Short enough that a leaked code is already dead.
CODE_TTL: Final[timedelta] = timedelta(minutes=10)

#: Five wrong answers inside one code's lifetime and pairing shuts until the window passes.
#:
#: Note carefully that this is a limit on *attempts against the server*, not attempts
#: against a particular code. Per-code counting is the intuitive design and it is worthless:
#: a wrong guess matches no stored fingerprint, so there is no record to increment, and the
#: attacker simply sweeps the keyspace paying nothing. Counting failures globally within the
#: pairing window is what actually turns 40 bits into 5 / 2^40 per window.
MAX_ATTEMPTS: Final[int] = 5


def fingerprint_of(secret: str) -> str:
    """The only form of a secret this system is willing to keep.

    Public because a repository needs it to look a token up by index. It is not a
    weakening: a fingerprint is what the database already holds, and the plaintext still
    never leaves this module except in the one moment it is handed to the device.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _matches(secret: str, fingerprint: str) -> bool:
    return hmac.compare_digest(fingerprint_of(secret), fingerprint)


# --------------------------------------------------------------------------- secrets
@dataclass(frozen=True, slots=True)
class DeviceToken:
    """A bearer token, in the one and only moment it exists in plaintext.

    Returned once, at pairing, and never again. `__repr__` is redacted so it cannot reach a
    log line or a traceback by accident — the same protection `Settings` gives the media key.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value.startswith(TOKEN_PREFIX):
            raise ValueError("a device token must carry the anv_ prefix")
        if len(self.value) < len(TOKEN_PREFIX) + 40:
            raise ValueError("device token is too short to be a 256-bit secret")

    @classmethod
    def issue(cls, random: RandomSource) -> Self:
        raw = base64.urlsafe_b64encode(random.token_bytes(TOKEN_BYTES)).decode().rstrip("=")
        return cls(f"{TOKEN_PREFIX}{raw}")

    @property
    def fingerprint(self) -> str:
        return fingerprint_of(self.value)

    def __repr__(self) -> str:
        return "DeviceToken(REDACTED)"

    def __str__(self) -> str:  # pragma: no cover - identical to repr, and for the same reason
        return "DeviceToken(REDACTED)"


@dataclass(frozen=True, slots=True)
class PairingCode:
    """Eight Crockford characters, shown as XXXX-XXXX and typed however the parent likes."""

    value: str

    def __post_init__(self) -> None:
        if len(self.value) != CODE_LENGTH:
            raise ValueError(f"a pairing code is {CODE_LENGTH} characters")
        if any(character not in _CROCKFORD for character in self.value):
            raise ValueError("a pairing code uses Crockford base32 only")

    @classmethod
    def issue(cls, random: RandomSource) -> Self:
        bits = int.from_bytes(random.token_bytes(CODE_BYTES), "big")
        characters = [_CROCKFORD[(bits >> (5 * i)) & 0x1F] for i in reversed(range(CODE_LENGTH))]
        return cls("".join(characters))

    @classmethod
    def parse(cls, typed: str) -> Result[Self, DomainError]:
        """Read what a human typed.

        Spaces, dashes and lower case are not mistakes to punish, and neither is typing O
        for zero. Anything still unreadable after that is `PAIRING_FAILED` — not a
        validation error, because saying "that is not even the right shape" is already a
        hint about which codes are real.
        """
        cleaned = "".join(
            _TRANSCRIPTION_FIXES.get(character, character)
            for character in typed.strip().upper()
            if character.isalnum()
        )
        try:
            return Ok(cls(cleaned))
        except ValueError:
            return Err(DomainError(ErrorCode.PAIRING_FAILED, "that code did not work"))

    @property
    def fingerprint(self) -> str:
        return fingerprint_of(self.value)

    def formatted(self) -> str:
        """XXXX-XXXX. The only form a person ever sees."""
        return f"{self.value[:4]}-{self.value[4:]}"

    def __repr__(self) -> str:
        return "PairingCode(REDACTED)"


# ------------------------------------------------------------------------- events
@dataclass(frozen=True, slots=True)
class DevicePaired(DomainEvent):
    family_id: str
    member_id: str

    def payload(self) -> dict[str, Any]:
        return {"family_id": self.family_id, "member_id": self.member_id}


@dataclass(frozen=True, slots=True)
class DeviceRevoked(DomainEvent):
    family_id: str

    def payload(self) -> dict[str, Any]:
        return {"family_id": self.family_id}


# ---------------------------------------------------------------------- aggregates
@dataclass(frozen=True, slots=True)
class Device:
    """One paired phone, tablet or share extension.

    `display_name` exists so revocation is a decision a parent can actually make: "the old
    iPad" is revocable, `dev-01H8...` is not.
    """

    id: DeviceId
    family_id: FamilyId
    member_id: MemberId
    display_name: str
    token_fingerprint: str
    created_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None
    pending_events: tuple[DomainEvent, ...] = ()

    def __post_init__(self) -> None:
        if not self.display_name.strip():
            raise ValueError("a device needs a name a person would recognise")
        if len(self.token_fingerprint) != 64:
            raise ValueError("token_fingerprint must be a sha256 hex digest")

    @classmethod
    def pair(
        cls,
        *,
        device_id: DeviceId,
        family_id: FamilyId,
        member_id: MemberId,
        display_name: str,
        token: DeviceToken,
        at: datetime,
    ) -> Self:
        return cls(
            id=device_id,
            family_id=family_id,
            member_id=member_id,
            display_name=display_name.strip(),
            token_fingerprint=token.fingerprint,
            created_at=at,
            pending_events=(
                DevicePaired(
                    aggregate_id=str(device_id),
                    occurred_at=at,
                    family_id=str(family_id),
                    member_id=str(member_id),
                ),
            ),
        )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def authenticates(self, presented: str) -> bool:
        """Constant-time. A revoked device authenticates nothing, ever again."""
        return not self.is_revoked and _matches(presented, self.token_fingerprint)

    def seen_at(self, at: datetime) -> Self:
        """Record use. Deliberately the only telemetry a device carries.

        No request count, no location, no app-open tally — PRD 8.5 applies to the family's
        own devices too. `last_seen_at` exists for one purpose: so "revoke the one I lost"
        can be answered with "the one last used on Tuesday".
        """
        return replace(self, last_seen_at=at, pending_events=())

    def revoke(self, at: datetime) -> Self:
        return replace(
            self,
            revoked_at=at,
            pending_events=(
                DeviceRevoked(
                    aggregate_id=str(self.id), occurred_at=at, family_id=str(self.family_id)
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class PairingRequest:
    """A code that has been shown, and has not yet become a device."""

    code_fingerprint: str
    family_id: FamilyId
    member_id: MemberId
    created_at: datetime
    expires_at: datetime
    claimed_at: datetime | None = None

    @classmethod
    def open(
        cls,
        *,
        code: PairingCode,
        family_id: FamilyId,
        member_id: MemberId,
        at: datetime,
        ttl: timedelta = CODE_TTL,
    ) -> Self:
        return cls(
            code_fingerprint=code.fingerprint,
            family_id=family_id,
            member_id=member_id,
            created_at=at,
            expires_at=at + ttl,
        )

    def is_open_at(self, at: datetime) -> bool:
        return self.claimed_at is None and at < self.expires_at

    def claim(self, code: PairingCode, at: datetime) -> Result[Self, DomainError]:
        """Consume this request, or refuse — with one message for every reason."""
        if not self.is_open_at(at) or not _matches(code.value, self.code_fingerprint):
            return Err(DomainError(ErrorCode.PAIRING_FAILED, "that code did not work"))
        return Ok(replace(self, claimed_at=at))


def pairing_is_locked(recent_failures: int) -> bool:
    """Whether pairing is shut because of failed attempts inside the current window.

    A pure policy function, so the rule is one readable line rather than a condition buried
    in a repository. See MAX_ATTEMPTS for why the count is global rather than per code.
    """
    return recent_failures >= MAX_ATTEMPTS


__all__ = [
    "CODE_LENGTH",
    "CODE_TTL",
    "MAX_ATTEMPTS",
    "TOKEN_PREFIX",
    "Device",
    "DevicePaired",
    "DeviceRevoked",
    "DeviceToken",
    "PairingCode",
    "PairingRequest",
    "fingerprint_of",
    "pairing_is_locked",
]
