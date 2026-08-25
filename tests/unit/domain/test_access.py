"""TASK-511 - the pairing primitives.

These are the parts where a mistake is silent. A token that is one bit shorter than intended
still works; a comparison that short-circuits still returns the right answer. So the tests
here are mostly about properties that cannot be observed by using the thing correctly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from anuvritti.domain.access import (
    CODE_LENGTH,
    CODE_TTL,
    MAX_ATTEMPTS,
    TOKEN_PREFIX,
    Device,
    DevicePaired,
    DeviceRevoked,
    DeviceToken,
    PairingCode,
    PairingRequest,
    fingerprint_of,
    pairing_is_locked,
)
from anuvritti.shared.identity import DeviceId, FamilyId, MemberId
from anuvritti.shared.randomness import (
    SequenceRandomSource,
    SystemRandomSource,
)

T0 = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
FAMILY = FamilyId("fam-1")
PAPA = MemberId("mem-papa")


def _token() -> DeviceToken:
    return DeviceToken.issue(SystemRandomSource())


def _device(**overrides) -> Device:
    defaults = {
        "device_id": DeviceId("dev-1"),
        "family_id": FAMILY,
        "member_id": PAPA,
        "display_name": "Papa's phone",
        "token": _token(),
        "at": T0,
    }
    return Device.pair(**{**defaults, **overrides})


class TestDeviceToken:
    def test_a_token_carries_enough_entropy_to_be_unguessable(self):
        """256 bits, base64url. The length is the security property, so assert the length."""
        token = _token()
        assert token.value.startswith(TOKEN_PREFIX)
        assert len(token.value) - len(TOKEN_PREFIX) >= 43

    def test_two_tokens_are_never_the_same(self):
        assert len({_token().value for _ in range(200)}) == 200

    def test_a_token_never_prints_itself(self):
        """The one protection that has to hold in a traceback nobody wrote on purpose."""
        token = _token()
        assert token.value not in repr(token)
        assert token.value not in str(token)
        assert token.value not in f"{token}"
        assert token.value not in repr({"authorization": token})

    def test_a_short_string_is_not_a_token(self):
        with pytest.raises(ValueError, match="too short"):
            DeviceToken(f"{TOKEN_PREFIX}abc")

    def test_a_token_without_the_prefix_is_refused(self):
        with pytest.raises(ValueError, match="prefix"):
            DeviceToken("x" * 60)

    def test_only_the_fingerprint_is_ever_stored(self):
        token = _token()
        device = _device(token=token)
        assert device.token_fingerprint == fingerprint_of(token.value)
        assert token.value not in device.token_fingerprint


class TestPairingCode:
    def test_a_code_is_eight_crockford_characters(self):
        code = PairingCode.issue(SystemRandomSource())
        assert len(code.value) == CODE_LENGTH
        assert set(code.value) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")

    def test_the_ambiguous_letters_are_absent_by_construction(self):
        """I, L, O and U never appear, so a parent reading aloud cannot produce them."""
        seen = {c for _ in range(500) for c in PairingCode.issue(SystemRandomSource()).value}
        assert not seen & set("ILOU")

    def test_it_is_shown_in_two_halves(self):
        assert PairingCode("ABCD1234").formatted() == "ABCD-1234"

    @pytest.mark.parametrize(
        "typed",
        ["ABCD1234", "abcd1234", "ABCD-1234", "  abcd 1234  ", "ABCD_1234"],
    )
    def test_a_parent_may_type_it_however_they_like(self, typed: str):
        assert PairingCode.parse(typed).unwrap().value == "ABCD1234"

    @pytest.mark.parametrize(
        "typed,expected",
        [("O1234567", "01234567"), ("I1234567", "11234567"), ("L1234567", "11234567")],
    )
    def test_the_letters_that_look_like_digits_are_read_as_digits(self, typed, expected):
        """Not leniency. Those glyphs are the same shape, and the code has no O, I or L."""
        assert PairingCode.parse(typed).unwrap().value == expected

    @pytest.mark.parametrize("typed", ["", "short", "waytoolongforacode", "!!!!!!!!"])
    def test_an_unreadable_code_fails_as_a_pairing_failure_not_a_validation_error(self, typed):
        """ "That is not even the right shape" is already a hint about which codes are real."""
        assert PairingCode.parse(typed).unwrap_err().code == "PAIRING_FAILED"

    def test_a_code_never_prints_itself(self):
        code = PairingCode("ABCD1234")
        assert "ABCD1234" not in repr(code)


class TestDevice:
    def test_pairing_records_who_and_when(self):
        device = _device()
        assert device.family_id == FAMILY
        assert device.member_id == PAPA
        assert isinstance(device.pending_events[0], DevicePaired)

    def test_a_device_authenticates_its_own_token_and_nothing_else(self):
        token = _token()
        device = _device(token=token)
        assert device.authenticates(token.value)
        assert not device.authenticates(_token().value)
        assert not device.authenticates("")

    def test_a_revoked_device_authenticates_nothing_ever_again(self):
        token = _token()
        device = _device(token=token).revoke(T0 + timedelta(days=1))
        assert device.is_revoked
        assert not device.authenticates(token.value)
        assert isinstance(device.pending_events[0], DeviceRevoked)

    def test_a_device_needs_a_name_a_person_would_recognise(self):
        with pytest.raises(ValueError, match="recognise"):
            _device(display_name="   ")

    def test_last_seen_is_the_only_thing_a_device_records_about_its_use(self):
        """PRD 8.5 applies to the family's own devices.

        There is no request count and no session log because "revoke the one I lost" is the
        only question this data exists to answer, and a date answers it.
        """
        device = _device().seen_at(T0 + timedelta(hours=3))
        assert device.last_seen_at == T0 + timedelta(hours=3)
        recorded = set(Device.__dataclass_fields__)
        assert not recorded & {"request_count", "sessions", "last_ip", "user_agent"}

    def test_recording_use_does_not_re_emit_the_pairing_event(self):
        """Otherwise every authenticated request would append DevicePaired to the audit log."""
        assert _device().seen_at(T0).pending_events == ()


class TestPairingRequest:
    def _open(self, code: PairingCode, at: datetime = T0) -> PairingRequest:
        return PairingRequest.open(code=code, family_id=FAMILY, member_id=PAPA, at=at)

    def test_the_right_code_claims_it(self):
        code = PairingCode("ABCD1234")
        claimed = self._open(code).claim(code, T0 + timedelta(minutes=1))
        assert claimed.is_ok()
        assert claimed.unwrap().claimed_at == T0 + timedelta(minutes=1)

    def test_a_claimed_code_cannot_be_claimed_twice(self):
        code = PairingCode("ABCD1234")
        once = self._open(code).claim(code, T0).unwrap()
        assert once.claim(code, T0).is_err()

    def test_a_code_dies_of_old_age(self):
        code = PairingCode("ABCD1234")
        assert self._open(code).claim(code, T0 + CODE_TTL + timedelta(seconds=1)).is_err()

    def test_the_wrong_code_is_refused(self):
        assert self._open(PairingCode("ABCD1234")).claim(PairingCode("ZZZZ9999"), T0).is_err()

    @pytest.mark.parametrize(
        "case",
        ["wrong code", "expired code", "already claimed"],
    )
    def test_every_refusal_says_exactly_the_same_thing(self, case: str):
        """Four reasons, one message. Telling them apart tells an attacker which codes exist."""
        code = PairingCode("ABCD1234")
        request = self._open(code)
        failure = {
            "wrong code": lambda: request.claim(PairingCode("ZZZZ9999"), T0),
            "expired code": lambda: request.claim(code, T0 + CODE_TTL + timedelta(seconds=1)),
            "already claimed": lambda: request.claim(code, T0).unwrap().claim(code, T0),
        }[case]().unwrap_err()
        assert (failure.code, failure.message) == ("PAIRING_FAILED", "that code did not work")


class TestLockout:
    def test_pairing_shuts_after_the_attempt_budget_is_spent(self):
        assert not pairing_is_locked(MAX_ATTEMPTS - 1)
        assert pairing_is_locked(MAX_ATTEMPTS)

    def test_the_budget_is_small_enough_to_matter(self):
        """40 bits and five guesses per window is 5 / 2^40. Twenty guesses would not be.

        This asserts the *number*, not the mechanism, because the number is the security
        argument: raising it later would silently weaken a code chosen to be short.
        """
        assert MAX_ATTEMPTS <= 5
        assert timedelta(minutes=15) >= CODE_TTL


class TestRandomness:
    def test_the_test_source_is_deterministic_and_the_real_one_is_not(self):
        first = SequenceRandomSource(b"\x01").token_bytes(8)
        second = SequenceRandomSource(b"\x01").token_bytes(8)
        assert first == second
        assert SystemRandomSource().token_bytes(16) != SystemRandomSource().token_bytes(16)

    def test_asking_for_nothing_is_a_mistake_not_an_empty_secret(self):
        for source in (SystemRandomSource(), SequenceRandomSource()):
            with pytest.raises(ValueError, match="positive count"):
                source.token_bytes(0)

    def test_the_sequence_source_still_fills_the_length_asked_for(self):
        """A short seed must not produce a short secret - that would be silently weaker."""
        assert len(SequenceRandomSource(b"\x01").token_bytes(32)) == 32

    def test_a_deterministic_source_cannot_be_the_default(self):
        """`build_container` defaults to the system source. Nothing else may.

        A `SequenceRandomSource` reaching production would make every device token in the
        family predictable, and nothing about the running system would look wrong.
        """
        import inspect

        from anuvritti.interfaces.http.container import build_container

        source = inspect.getsource(build_container)
        assert "SystemRandomSource()" in source
        assert "SequenceRandomSource" not in source
