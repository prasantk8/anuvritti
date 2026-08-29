"""PRD 20, 44 and 47 - a Future Inbox seal is an ethical boundary."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

import pytest

from anuvritti.domain.inbox import FutureMessage, MessageCare, OpeningKey, PresentedArtifact
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, FutureMessageId, MemberId

pytestmark = pytest.mark.constitution

NOW = datetime(2026, 8, 28, 20, 15, tzinfo=UTC)
FAMILY = FamilyId("fam-1")
CHILD = ChildId("chi-1")
PAPA = MemberId("mem-papa")


def seal(*, key: OpeningKey, care: MessageCare = MessageCare.ORDINARY) -> FutureMessage:
    return FutureMessage.seal_written(
        message_id=FutureMessageId("inbox-1"),
        family_id=FAMILY,
        child_id=CHILD,
        sealed_by=PAPA,
        opening_key=key,
        care=care,
        text="For the day you need these words.",
        at=NOW,
    ).unwrap()


class TestSensitiveMessagesAreNeverMachineTriggered:
    @pytest.mark.parametrize(
        "key",
        [
            OpeningKey.FIFTH_BIRTHDAY,
            OpeningKey.TENTH_BIRTHDAY,
            OpeningKey.THIRTEENTH_BIRTHDAY,
            OpeningKey.EIGHTEENTH_BIRTHDAY,
        ],
    )
    def test_the_aggregate_refuses_an_automatic_key_at_sealing_time(self, key):
        result = FutureMessage.seal_written(
            message_id=FutureMessageId("inbox-sensitive"),
            family_id=FAMILY,
            child_id=CHILD,
            sealed_by=PAPA,
            opening_key=key,
            care=MessageCare.SENSITIVE,
            text="Private words for a difficult day.",
            at=NOW,
        )

        assert result.unwrap_err().code is ErrorCode.PERMISSION_DENIED

    @pytest.mark.parametrize("key", [OpeningKey.LEAVING_HOME, OpeningKey.WHENEVER_YOU_CHOOSE])
    def test_a_parent_may_seal_sensitive_words_behind_a_human_key(self, key):
        assert seal(key=key, care=MessageCare.SENSITIVE).opening_key is key


class TestTheParentsSideDoesNotTurnLoveIntoScorekeeping:
    def test_it_says_only_sealed(self):
        view = seal(key=OpeningKey.FIFTH_BIRTHDAY).for_parent()

        assert view.label == "sealed"
        assert {field.name for field in fields(view)} == {"label"}

    def test_it_does_not_reveal_the_words_or_when_the_child_will_read_them(self):
        message = seal(key=OpeningKey.EIGHTEENTH_BIRTHDAY)
        rendered = message.for_parent().to_dict()

        assert rendered == {"status": "sealed"}
        assert "eighteen" not in str(rendered).lower()


class TestASealWithNoProofNeverOpens:
    def test_an_altered_message_is_refused_instead_of_opened_with_a_warning(self):
        message = seal(key=OpeningKey.LEAVING_HOME)

        result = message.open_by_choice(
            PresentedArtifact.written("Plausible replacement words."),
            opening_key=OpeningKey.LEAVING_HOME,
            opened_by=PAPA,
            at=NOW,
        )

        assert result.unwrap_err().code is ErrorCode.CONFLICT

    def test_the_provenance_record_identifies_one_artifact_and_covers_it_exactly(self):
        message = seal(key=OpeningKey.FIFTH_BIRTHDAY)

        assert message.ledger.message_id == message.id
        assert len(message.ledger.entries) == 1
        assert message.ledger.entry.source_id == str(message.id)
