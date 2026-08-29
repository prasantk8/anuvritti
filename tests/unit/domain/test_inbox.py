"""TASK-806 - messages kept closed until the moment their parent chose."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from anuvritti.domain.inbox import (
    ArtifactKind,
    FutureMessage,
    MessageCare,
    OpeningKey,
    ParentSealedView,
    PresentedArtifact,
    SealedArtifact,
    SealLedger,
)
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, FutureMessageId, MediaId, MemberId

SEALED_AT = datetime(2026, 8, 28, 20, 15, tzinfo=UTC)
FAMILY = FamilyId("fam-1")
CHILD = ChildId("chi-1")
PAPA = MemberId("mem-papa")
MESSAGE = FutureMessageId("inbox-1")


def a_letter(
    *,
    opening_key: OpeningKey = OpeningKey.FIFTH_BIRTHDAY,
    care: MessageCare = MessageCare.ORDINARY,
    text: str = "You called the moon your night-time sun.",
) -> FutureMessage:
    return FutureMessage.seal_written(
        message_id=MESSAGE,
        family_id=FAMILY,
        child_id=CHILD,
        sealed_by=PAPA,
        opening_key=opening_key,
        care=care,
        text=text,
        at=SEALED_AT,
    ).unwrap()


class TestSealing:
    def test_written_words_are_fingerprinted_without_normalising_them(self):
        composed = a_letter(text="क़लम")
        decomposed = a_letter(text="क़लम")

        assert composed.ledger.entry.content_hash != decomposed.ledger.entry.content_hash
        assert composed.ledger.entry.kind is ArtifactKind.WRITTEN

    def test_a_recording_cites_the_real_media_and_its_bytes(self):
        message = FutureMessage.seal_recording(
            message_id=MESSAGE,
            family_id=FAMILY,
            child_id=CHILD,
            sealed_by=PAPA,
            opening_key=OpeningKey.TENTH_BIRTHDAY,
            care=MessageCare.ORDINARY,
            media_id=MediaId("med-papas-voice"),
            content=b"real recording bytes",
            at=SEALED_AT,
        ).unwrap()

        assert message.ledger.entry.kind is ArtifactKind.RECORDING
        assert message.ledger.entry.source_id == "med-papas-voice"
        assert message.ledger.entry.byte_size == len(b"real recording bytes")
        assert len(message.ledger.entry.content_hash) == 64

    @pytest.mark.parametrize("text", ["", "   ", "\n\t"])
    def test_a_blank_letter_is_not_a_message(self, text):
        result = FutureMessage.seal_written(
            message_id=MESSAGE,
            family_id=FAMILY,
            child_id=CHILD,
            sealed_by=PAPA,
            opening_key=OpeningKey.FIFTH_BIRTHDAY,
            care=MessageCare.ORDINARY,
            text=text,
            at=SEALED_AT,
        )
        assert result.unwrap_err().code is ErrorCode.VALIDATION_FAILED

    def test_an_empty_recording_is_not_a_recording(self):
        result = FutureMessage.seal_recording(
            message_id=MESSAGE,
            family_id=FAMILY,
            child_id=CHILD,
            sealed_by=PAPA,
            opening_key=OpeningKey.FIFTH_BIRTHDAY,
            care=MessageCare.ORDINARY,
            media_id=MediaId("med-empty"),
            content=b"",
            at=SEALED_AT,
        )
        assert result.unwrap_err().code is ErrorCode.VALIDATION_FAILED

    def test_the_seal_contains_no_plaintext_or_recording_bytes(self):
        private_words = "a sentence that belongs only to this family"
        message = a_letter(text=private_words)

        assert private_words not in repr(message)
        assert private_words not in repr(message.ledger)
        assert not hasattr(message, "text")
        assert not hasattr(message, "content")

    def test_the_provenance_ledger_is_portable_without_carrying_the_message(self):
        private_words = "मेरी प्यारी बेटी"
        ledger = a_letter(text=private_words).ledger.to_dict()

        assert ledger["schema"] == "anuvritti.future-inbox-provenance.v1"
        assert ledger["message_id"] == "inbox-1"
        assert ledger["sealed_at"] == SEALED_AT.isoformat()
        assert private_words not in str(ledger)
        entries = ledger["entries"]
        assert isinstance(entries, list)
        assert isinstance(entries[0], dict)
        assert set(entries[0]) == {
            "kind",
            "source_id",
            "content_hash",
            "byte_size",
        }

    def test_a_seal_needs_an_absolute_instant(self):
        result = FutureMessage.seal_written(
            message_id=MESSAGE,
            family_id=FAMILY,
            child_id=CHILD,
            sealed_by=PAPA,
            opening_key=OpeningKey.FIFTH_BIRTHDAY,
            care=MessageCare.ORDINARY,
            text="words",
            at=SEALED_AT.replace(tzinfo=None),
        )

        assert result.unwrap_err().code is ErrorCode.VALIDATION_FAILED


class TestConstructionCannotBypassTheSeal:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"source_id": ""},
            {"byte_size": 0},
            {"content_hash": "not-a-digest"},
        ],
    )
    def test_an_invalid_provenance_entry_cannot_be_constructed(self, overrides):
        values = {
            "kind": ArtifactKind.WRITTEN,
            "source_id": "inbox-1",
            "content_hash": "0" * 64,
            "byte_size": 1,
        }
        with pytest.raises(ValueError):
            SealedArtifact(**{**values, **overrides})

    def test_a_ledger_with_a_gap_or_padding_is_not_a_ledger(self):
        with pytest.raises(ValueError, match="exactly one"):
            SealLedger(message_id=MESSAGE, sealed_at=SEALED_AT, entries=())

    def test_the_parent_projection_cannot_be_given_a_more_revealing_label(self):
        with pytest.raises(ValueError, match="only says sealed"):
            ParentSealedView("opens at eighteen")

    def test_a_ledger_from_another_message_is_refused(self):
        message = a_letter()
        with pytest.raises(ValueError, match="belong"):
            replace(message, id=FutureMessageId("inbox-2"))

    def test_a_ledger_from_another_instant_is_refused(self):
        message = a_letter()
        with pytest.raises(ValueError, match="moment"):
            replace(
                message, ledger=replace(message.ledger, sealed_at=SEALED_AT + timedelta(seconds=1))
            )

    def test_direct_construction_cannot_put_sensitive_words_behind_a_calendar(self):
        with pytest.raises(ValueError, match="sensitive"):
            replace(a_letter(), care=MessageCare.SENSITIVE)


class TestCalendarOpening:
    @pytest.mark.parametrize(
        "key,years",
        [
            (OpeningKey.FIFTH_BIRTHDAY, 5),
            (OpeningKey.TENTH_BIRTHDAY, 10),
            (OpeningKey.THIRTEENTH_BIRTHDAY, 13),
            (OpeningKey.EIGHTEENTH_BIRTHDAY, 18),
        ],
    )
    def test_each_age_key_opens_on_the_birthday_the_parent_chose(self, key, years):
        message = a_letter(opening_key=key)
        born_on = date(2021, 9, 2)
        due = date(2021 + years, 9, 2)

        assert message.open_automatically(
            PresentedArtifact.written("You called the moon your night-time sun."),
            child_born_on=born_on,
            on=due - timedelta(days=1),
            at=SEALED_AT,
        ).is_err()
        assert message.open_automatically(
            PresentedArtifact.written("You called the moon your night-time sun."),
            child_born_on=born_on,
            on=due,
            at=SEALED_AT,
        ).is_ok()

    def test_a_leap_day_child_gets_the_message_on_the_last_day_of_february(self):
        message = a_letter(opening_key=OpeningKey.FIFTH_BIRTHDAY)

        assert message.open_automatically(
            PresentedArtifact.written("You called the moon your night-time sun."),
            child_born_on=date(2024, 2, 29),
            on=date(2029, 2, 28),
            at=SEALED_AT,
        ).is_ok()

    @pytest.mark.parametrize("key", [OpeningKey.LEAVING_HOME, OpeningKey.WHENEVER_YOU_CHOOSE])
    def test_a_human_moment_can_never_be_inferred_from_a_calendar(self, key):
        message = a_letter(opening_key=key)

        result = message.open_automatically(
            PresentedArtifact.written("You called the moon your night-time sun."),
            child_born_on=date(2021, 9, 2),
            on=date(2099, 1, 1),
            at=SEALED_AT,
        )

        assert result.unwrap_err().code is ErrorCode.PERMISSION_DENIED


class TestHumanOpening:
    def test_leaving_home_opens_only_when_a_person_presents_that_exact_key(self):
        message = a_letter(opening_key=OpeningKey.LEAVING_HOME)

        wrong = message.open_by_choice(
            PresentedArtifact.written("You called the moon your night-time sun."),
            opening_key=OpeningKey.WHENEVER_YOU_CHOOSE,
            opened_by=PAPA,
            at=SEALED_AT,
        )
        opened = message.open_by_choice(
            PresentedArtifact.written("You called the moon your night-time sun."),
            opening_key=OpeningKey.LEAVING_HOME,
            opened_by=PAPA,
            at=SEALED_AT,
        ).unwrap()

        assert wrong.unwrap_err().code is ErrorCode.PERMISSION_DENIED
        assert opened.opened_by == str(PAPA)

    def test_whenever_you_choose_belongs_to_the_child(self):
        message = a_letter(opening_key=OpeningKey.WHENEVER_YOU_CHOOSE)

        refused = message.open_by_choice(
            PresentedArtifact.written("You called the moon your night-time sun."),
            opening_key=OpeningKey.WHENEVER_YOU_CHOOSE,
            opened_by=PAPA,
            at=SEALED_AT,
        )
        opened = message.open_by_choice(
            PresentedArtifact.written("You called the moon your night-time sun."),
            opening_key=OpeningKey.WHENEVER_YOU_CHOOSE,
            opened_by=CHILD,
            at=SEALED_AT,
        ).unwrap()

        assert refused.unwrap_err().code is ErrorCode.PERMISSION_DENIED
        assert opened.opened_by == str(CHILD)


class TestExactArtifactOpening:
    def test_the_exact_written_bytes_come_back(self):
        words = "Beta, tum meri sabse khoobsurat kahaani ho.\n— Papa"
        message = a_letter(text=words)

        opened = message.open_automatically(
            PresentedArtifact.written(words),
            child_born_on=date(2021, 1, 1),
            on=date(2026, 1, 1),
            at=SEALED_AT,
        ).unwrap()

        assert opened.written_text == words
        assert opened.content == words.encode("utf-8")

    def test_one_changed_character_breaks_the_seal(self):
        message = a_letter()

        result = message.open_automatically(
            PresentedArtifact.written("You called the moon a night-time sun."),
            child_born_on=date(2021, 1, 1),
            on=date(2026, 1, 1),
            at=SEALED_AT,
        )

        error = result.unwrap_err()
        assert error.code is ErrorCode.CONFLICT
        assert "does not match" in error.message
        assert "content" not in error.details

    def test_a_different_recording_cannot_open_under_the_right_media_id(self):
        message = FutureMessage.seal_recording(
            message_id=MESSAGE,
            family_id=FAMILY,
            child_id=CHILD,
            sealed_by=PAPA,
            opening_key=OpeningKey.TENTH_BIRTHDAY,
            care=MessageCare.ORDINARY,
            media_id=MediaId("med-papas-voice"),
            content=b"the voice sealed today",
            at=SEALED_AT,
        ).unwrap()

        result = message.open_automatically(
            PresentedArtifact.recording(MediaId("med-papas-voice"), b"a replacement voice"),
            child_born_on=date(2016, 1, 1),
            on=date(2026, 1, 1),
            at=SEALED_AT,
        )

        assert result.unwrap_err().code is ErrorCode.CONFLICT

    def test_a_verified_recording_opens_as_audio_not_as_a_transcript(self):
        message = FutureMessage.seal_recording(
            message_id=MESSAGE,
            family_id=FAMILY,
            child_id=CHILD,
            sealed_by=PAPA,
            opening_key=OpeningKey.TENTH_BIRTHDAY,
            care=MessageCare.ORDINARY,
            media_id=MediaId("med-papas-voice"),
            content=b"the voice sealed today",
            at=SEALED_AT,
        ).unwrap()

        opened = message.open_automatically(
            PresentedArtifact.recording(MediaId("med-papas-voice"), b"the voice sealed today"),
            child_born_on=date(2016, 1, 1),
            on=date(2026, 1, 1),
            at=SEALED_AT,
        ).unwrap()

        assert opened.content == b"the voice sealed today"
        assert opened.written_text is None

    @pytest.mark.parametrize(
        "at", [SEALED_AT - timedelta(seconds=1), SEALED_AT.replace(tzinfo=None)]
    )
    def test_opening_needs_an_absolute_instant_after_the_seal(self, at):
        message = a_letter(opening_key=OpeningKey.LEAVING_HOME)

        result = message.open_by_choice(
            PresentedArtifact.written("You called the moon your night-time sun."),
            opening_key=OpeningKey.LEAVING_HOME,
            opened_by=PAPA,
            at=at,
        )

        assert result.unwrap_err().code is ErrorCode.VALIDATION_FAILED

    def test_kind_and_source_are_part_of_the_proof_not_only_the_hash(self):
        sealed = SealedArtifact.from_written(MESSAGE, "same bytes").unwrap()
        presented = PresentedArtifact.recording(MediaId("med-1"), b"same bytes")

        assert sealed.verify(presented).is_err()
