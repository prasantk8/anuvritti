"""TASK-820 — the family can authenticate a seal years later, entirely offline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet

from anuvritti.adapters.authenticity import family_authentication_tag, family_key_id
from anuvritti.adapters.inbox.authenticity import FutureInboxLedgerAuthenticator
from anuvritti.adapters.persistence.inbox import AtomicEncryptedFutureInboxStore
from anuvritti.domain.inbox import FutureMessage, MessageCare, OpeningKey, PresentedArtifact
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, FutureMessageId, MemberId

NOW = datetime(2026, 8, 29, 9, 30, tzinfo=UTC)
KEY = b"one offline family authenticity key" * 2


def message(message_id: str = "inbox-1", text: str = "तुम हमेशा घर लौट सकती हो।") -> FutureMessage:
    return FutureMessage.seal_written(
        message_id=FutureMessageId(message_id),
        family_id=FamilyId("fam-1"),
        child_id=ChildId("chi-1"),
        sealed_by=MemberId("mem-papa"),
        opening_key=OpeningKey.LEAVING_HOME,
        care=MessageCare.SENSITIVE,
        text=text,
        at=NOW,
    ).unwrap()


def write_ledger(path: Path, sealed: FutureMessage) -> Path:
    path.write_text(
        json.dumps(sealed.ledger.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def test_family_key_authenticates_a_portable_ledger_without_the_archive(tmp_path):
    ledger = write_ledger(tmp_path / "inbox-1.ledger.json", message())
    anchor = tmp_path / "inbox-1.anchor.json"
    authenticator = FutureInboxLedgerAuthenticator()

    authenticator.anchor(ledger, key=KEY, destination=anchor).unwrap()

    assert authenticator.authenticate(ledger, key=KEY, anchor=anchor).is_ok()
    payload = json.loads(anchor.read_text())
    assert payload["schema"] == "anuvritti.future-inbox-anchor.v2"
    assert payload["key_id"] == family_key_id(KEY)
    assert payload["message_id"] == "inbox-1"
    assert set(payload) == {
        "schema",
        "key_id",
        "ledger",
        "message_id",
        "ledger_sha256",
        "hmac_sha256",
    }


def test_the_ledger_loaded_from_atomic_persistence_is_the_one_anchored(tmp_path, db, seeded_family):
    sealed = message()
    inbox = AtomicEncryptedFutureInboxStore(
        root=tmp_path / "future-inbox",
        connection=db,
        encryption_key=Fernet.generate_key().decode(),
    )
    inbox.save(
        sealed,
        PresentedArtifact.written("तुम हमेशा घर लौट सकती हो।", message_id=FutureMessageId("inbox-1")),
    ).unwrap()
    persisted = inbox.ledger(FutureMessageId("inbox-1")).unwrap()
    ledger = tmp_path / "persisted.ledger.json"
    ledger.write_text(json.dumps(persisted.to_dict(), indent=2, sort_keys=True) + "\n")
    anchor = tmp_path / "persisted.anchor.json"

    authenticator = FutureInboxLedgerAuthenticator()
    authenticator.anchor(ledger, key=KEY, destination=anchor).unwrap()

    assert authenticator.authenticate(ledger, key=KEY, anchor=anchor).is_ok()


def test_legacy_unversioned_inbox_anchor_remains_authentic(tmp_path):
    ledger = write_ledger(tmp_path / "inbox-1.ledger.json", message())
    anchor = tmp_path / "inbox-1.anchor.json"
    authenticator = FutureInboxLedgerAuthenticator()
    authenticator.anchor(ledger, key=KEY, destination=anchor).unwrap()
    payload = json.loads(anchor.read_text())
    payload["schema"] = "anuvritti.future-inbox-anchor.v1"
    payload.pop("key_id")
    anchor.write_text(json.dumps(payload))

    assert authenticator.authenticate(ledger, key=KEY, anchor=anchor).is_ok()


def test_replacing_both_message_and_digest_cannot_reuse_the_original_anchor(tmp_path):
    ledger = write_ledger(tmp_path / "seal.ledger.json", message())
    anchor = tmp_path / "seal.anchor.json"
    authenticator = FutureInboxLedgerAuthenticator()
    authenticator.anchor(ledger, key=KEY, destination=anchor).unwrap()

    write_ledger(ledger, message(text="convincing replacement words"))

    result = authenticator.authenticate(ledger, key=KEY, anchor=anchor)
    assert result.unwrap_err().code is ErrorCode.CONFLICT


def test_a_different_message_identity_cannot_borrow_the_anchor(tmp_path):
    ledger = write_ledger(tmp_path / "seal.ledger.json", message())
    anchor = tmp_path / "seal.anchor.json"
    authenticator = FutureInboxLedgerAuthenticator()
    authenticator.anchor(ledger, key=KEY, destination=anchor).unwrap()

    write_ledger(ledger, message(message_id="inbox-2"))

    assert authenticator.authenticate(ledger, key=KEY, anchor=anchor).is_err()


def test_wrong_or_short_family_keys_are_error_values(tmp_path):
    ledger = write_ledger(tmp_path / "seal.ledger.json", message())
    anchor = tmp_path / "seal.anchor.json"
    authenticator = FutureInboxLedgerAuthenticator()
    authenticator.anchor(ledger, key=KEY, destination=anchor).unwrap()

    wrong = authenticator.authenticate(
        ledger, key=b"another offline family key value!!", anchor=anchor
    )
    short = authenticator.anchor(ledger, key=b"short", destination=tmp_path / "bad.anchor.json")

    assert wrong.unwrap_err().code is ErrorCode.CONFLICT
    assert short.unwrap_err().code is ErrorCode.VALIDATION_FAILED


def test_anchor_contains_neither_private_words_nor_the_key(tmp_path):
    private_words = "क़लम और क़लम दोनों वैसे ही रखना"
    ledger = write_ledger(tmp_path / "seal.ledger.json", message(text=private_words))
    anchor = tmp_path / "seal.anchor.json"

    FutureInboxLedgerAuthenticator().anchor(ledger, key=KEY, destination=anchor).unwrap()

    body = anchor.read_bytes()
    assert private_words.encode() not in body
    assert KEY not in body


def test_malformed_or_non_inbox_ledgers_are_never_anchored(tmp_path):
    malformed = tmp_path / "bad.json"
    malformed.write_text('{"schema":"something-else"}')

    result = FutureInboxLedgerAuthenticator().anchor(
        malformed, key=KEY, destination=tmp_path / "anchor.json"
    )

    assert result.unwrap_err().code is ErrorCode.VALIDATION_FAILED
    assert not (tmp_path / "anchor.json").exists()


def test_film_and_inbox_receipts_use_distinct_authentication_contexts():
    document = b"the same exact portable bytes"

    assert family_authentication_tag(
        document, key=KEY, context=b"anuvritti-render-receipt-v1\0"
    ) != family_authentication_tag(document, key=KEY, context=b"anuvritti-future-inbox-ledger-v1\0")
