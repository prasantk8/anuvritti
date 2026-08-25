"""Pairing and authentication (HARDENING 5.1, TASK-511).

Four things happen here and nothing else: a device is paired, a code is opened, a token is
resolved to the family it belongs to, and a lost phone is revoked.

The pairing story is deliberately the one a family can actually perform. There is no email,
no password to invent and forget, and no account to recover. The first device is paired by
the act of creating the family — bootstrap *is* the pairing. Every device after that reads
eight characters off a phone that is already inside the house, which is a real second factor:
you have to be standing there.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from anuvritti.application.ports import (
    DeviceRepository,
    EventPublisher,
    FamilyRepository,
    PairingRepository,
    UnitOfWork,
)
from anuvritti.domain.access import (
    CODE_TTL,
    Device,
    DeviceToken,
    PairingCode,
    PairingRequest,
    fingerprint_of,
    pairing_is_locked,
)
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import DeviceId, FamilyId, IdGenerator, MemberId
from anuvritti.shared.randomness import RandomSource
from anuvritti.shared.result import Err, Ok, Result

#: One error for every way authentication can fail. See domain/access.py for why.
_NO = DomainError(ErrorCode.UNAUTHENTICATED, "this device is not paired with a family")
_PAIRING_FAILED = DomainError(ErrorCode.PAIRING_FAILED, "that code did not work")


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """Who the caller is, decided entirely by the token and never by the request body.

    Every endpoint takes its `family_id` and its actor from one of these. That is the whole
    of HARDENING 5.1: there is no code path left where a request can name someone else.
    """

    device_id: DeviceId
    family_id: FamilyId
    member_id: MemberId

    def owns(self, family_id: str | None) -> bool:
        """Whether a family named in a request is the one this token belongs to."""
        return family_id is None or family_id == str(self.family_id)


@dataclass(frozen=True, slots=True)
class PairedDevice:
    """A device and the token it will never be shown again."""

    device: Device
    token: DeviceToken


class PairDeviceUseCase:
    """Issue a token and record the device. Used by bootstrap and by claiming a code alike."""

    def __init__(
        self,
        *,
        devices: DeviceRepository,
        events: EventPublisher,
        clock: Clock,
        ids: IdGenerator,
        random: RandomSource,
        uow: UnitOfWork,
    ) -> None:
        self._devices = devices
        self._events = events
        self._clock = clock
        self._ids = ids
        self._random = random
        self._uow = uow

    def execute(
        self, *, family_id: FamilyId, member_id: MemberId, display_name: str
    ) -> Result[PairedDevice, DomainError]:
        token = DeviceToken.issue(self._random)
        try:
            device = Device.pair(
                device_id=DeviceId(self._ids.new_id()),
                family_id=family_id,
                member_id=member_id,
                display_name=display_name,
                token=token,
                at=self._clock.now(),
            )
        except ValueError as exc:
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, str(exc)))

        with self._uow:
            saved = self._devices.save(device)
            if saved.is_err():
                self._uow.rollback()
                return Err(saved.unwrap_err())
            self._events.publish(device.pending_events, family_id=family_id)
            self._uow.commit()
        return Ok(PairedDevice(device=device, token=token))


class OpenPairingUseCase:
    """Show a code on a device that is already trusted."""

    def __init__(
        self,
        *,
        pairings: PairingRepository,
        clock: Clock,
        random: RandomSource,
        uow: UnitOfWork,
    ) -> None:
        self._pairings = pairings
        self._clock = clock
        self._random = random
        self._uow = uow

    def execute(self, identity: DeviceIdentity) -> Result[PairingCode, DomainError]:
        now = self._clock.now()
        code = PairingCode.issue(self._random)
        request = PairingRequest.open(
            code=code, family_id=identity.family_id, member_id=identity.member_id, at=now
        )
        with self._uow:
            saved = self._pairings.save(request)
            if saved.is_err():
                self._uow.rollback()
                return Err(saved.unwrap_err())
            self._uow.commit()
        return Ok(code)


class ClaimPairingUseCase:
    """Turn eight typed characters into a paired device, or refuse without explaining."""

    def __init__(
        self,
        *,
        pairings: PairingRepository,
        families: FamilyRepository,
        pair_device: PairDeviceUseCase,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._pairings = pairings
        self._families = families
        self._pair_device = pair_device
        self._clock = clock
        self._uow = uow

    def execute(self, *, typed_code: str, display_name: str) -> Result[PairedDevice, DomainError]:
        now = self._clock.now()

        # The lockout is checked before anything else, so a locked server does no work at
        # all - not a lookup, not a hash. Lockout has to be cheap or it is a load amplifier.
        if pairing_is_locked(self._pairings.failures_since(now - CODE_TTL)):
            return Err(_PAIRING_FAILED)

        parsed = PairingCode.parse(typed_code)
        if parsed.is_err():
            self._record(succeeded=False, at=now)
            return Err(_PAIRING_FAILED)
        code = parsed.unwrap()

        found = self._pairings.find_by_fingerprint(fingerprint_of(code.value))
        if found.is_err():
            return Err(found.unwrap_err())
        request = found.unwrap()
        if request is None:
            self._record(succeeded=False, at=now)
            return Err(_PAIRING_FAILED)

        claimed = request.claim(code, now)
        if claimed.is_err():
            self._record(succeeded=False, at=now)
            return Err(_PAIRING_FAILED)

        # The family the code was opened on must still exist. It is a real case: a code
        # survives in the table a few minutes longer than a family a parent just deleted.
        if self._families.get(request.family_id).is_err():
            self._record(succeeded=False, at=now)
            return Err(_PAIRING_FAILED)

        with self._uow:
            consumed = self._pairings.save(claimed.unwrap())
            if consumed.is_err():
                self._uow.rollback()
                return Err(consumed.unwrap_err())
            self._uow.commit()

        paired = self._pair_device.execute(
            family_id=request.family_id,
            member_id=request.member_id,
            display_name=display_name,
        )
        self._record(succeeded=paired.is_ok(), at=now)
        return paired

    def _record(self, *, succeeded: bool, at: datetime) -> None:
        self._pairings.record_attempt(succeeded=succeeded, at=at)


class AuthenticateDeviceUseCase:
    """Resolve a presented bearer token to an identity, or to nothing.

    Two steps, on purpose. The indexed lookup is by fingerprint so the plaintext token never
    appears in a query; the confirmation is `hmac.compare_digest` inside the aggregate, so a
    fingerprint collision - or a repository that got clever about matching - still cannot
    authenticate anyone.
    """

    def __init__(self, *, devices: DeviceRepository, clock: Clock) -> None:
        self._devices = devices
        self._clock = clock

    def execute(self, presented: str | None) -> Result[DeviceIdentity, DomainError]:
        token = (presented or "").strip()
        if not token:
            return Err(_NO)

        found = self._devices.find_by_fingerprint(fingerprint_of(token))
        if found.is_err():
            return Err(_NO)
        device = found.unwrap()
        if device is None or not device.authenticates(token):
            return Err(_NO)

        self._devices.save(device.seen_at(self._clock.now()))
        return Ok(
            DeviceIdentity(
                device_id=device.id, family_id=device.family_id, member_id=device.member_id
            )
        )


class ListDevicesUseCase:
    """What is paired, so a parent can see it and decide."""

    def __init__(self, *, devices: DeviceRepository) -> None:
        self._devices = devices

    def execute(self, identity: DeviceIdentity) -> Result[Sequence[Device], DomainError]:
        return self._devices.list_for_family(identity.family_id)


class RevokeDeviceUseCase:
    """Cut a lost phone off.

    A device may only revoke inside its own family, and the current device may revoke itself
    - which is what "sign out" means when there is no account to sign out of.
    """

    def __init__(
        self,
        *,
        devices: DeviceRepository,
        events: EventPublisher,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._devices = devices
        self._events = events
        self._clock = clock
        self._uow = uow

    def execute(
        self, identity: DeviceIdentity, *, device_id: DeviceId
    ) -> Result[Device, DomainError]:
        found = self._devices.get(device_id)
        if found.is_err():
            return Err(found.unwrap_err())
        device = found.unwrap()
        if device.family_id != identity.family_id:
            # Not "not found in your family" - the same answer a stranger's id would get,
            # so the response never confirms that some other family's device exists.
            return Err(DomainError(ErrorCode.MEMBER_NOT_FOUND, "no such device"))

        revoked = device.revoke(self._clock.now())
        with self._uow:
            saved = self._devices.save(revoked)
            if saved.is_err():
                self._uow.rollback()
                return Err(saved.unwrap_err())
            self._events.publish(revoked.pending_events, family_id=identity.family_id)
            self._uow.commit()
        return Ok(revoked)


__all__ = [
    "AuthenticateDeviceUseCase",
    "ClaimPairingUseCase",
    "DeviceIdentity",
    "ListDevicesUseCase",
    "OpenPairingUseCase",
    "PairDeviceUseCase",
    "PairedDevice",
    "RevokeDeviceUseCase",
]
