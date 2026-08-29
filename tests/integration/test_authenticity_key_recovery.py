"""TASK-823 — family authenticity keys can be recovered and rotated without content."""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from pathlib import Path

from anuvritti.adapters.authenticity import family_key_id
from anuvritti.adapters.key_recovery import FamilyAuthenticityKeyCeremony
from anuvritti.shared.errors import ErrorCode

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
PASSPHRASE = b"four mangoes cross the monsoon safely"
KEY = b"the first family authenticity key!!"


def test_encrypted_second_copy_recovers_exact_key_with_private_permissions(tmp_path):
    bundle = tmp_path / "family-key-v1.recovery.json"
    recovered = tmp_path / "recovered-family.key"
    ceremony = FamilyAuthenticityKeyCeremony()

    backup = ceremony.backup(
        key=KEY,
        version=1,
        passphrase=PASSPHRASE,
        destination=bundle,
        created_at=NOW,
    ).unwrap()
    result = ceremony.recover(
        bundle=bundle,
        passphrase=PASSPHRASE,
        destination=recovered,
    ).unwrap()

    assert backup.key_id == family_key_id(KEY)
    assert result.version == 1
    assert recovered.read_bytes() == KEY
    assert stat.S_IMODE(recovered.stat().st_mode) == 0o600
    body = bundle.read_bytes()
    assert KEY not in body
    assert PASSPHRASE not in body


def test_wrong_passphrase_or_changed_bundle_fails_without_writing_a_key(tmp_path):
    bundle = tmp_path / "family-key-v1.recovery.json"
    ceremony = FamilyAuthenticityKeyCeremony()
    ceremony.backup(
        key=KEY,
        version=1,
        passphrase=PASSPHRASE,
        destination=bundle,
        created_at=NOW,
    ).unwrap()

    wrong_destination = tmp_path / "wrong.key"
    wrong = ceremony.recover(
        bundle=bundle,
        passphrase=b"a different long recovery phrase",
        destination=wrong_destination,
    )
    payload = json.loads(bundle.read_text())
    payload["key_version"] = 2
    bundle.write_text(json.dumps(payload))
    changed_destination = tmp_path / "changed.key"
    changed = ceremony.recover(
        bundle=bundle,
        passphrase=PASSPHRASE,
        destination=changed_destination,
    )

    assert wrong.unwrap_err().code is ErrorCode.CONFLICT
    assert changed.unwrap_err().code is ErrorCode.CONFLICT
    assert not wrong_destination.exists()
    assert not changed_destination.exists()


def test_rotation_keeps_separate_versioned_recovery_bundles(tmp_path):
    ceremony = FamilyAuthenticityKeyCeremony()
    first_key = tmp_path / "family-v1.key"
    first_bundle = tmp_path / "family-v1.recovery.json"
    second_key = tmp_path / "family-v2.key"
    second_bundle = tmp_path / "family-v2.recovery.json"

    first = ceremony.rotate(
        version=1,
        passphrase=PASSPHRASE,
        key_destination=first_key,
        backup_destination=first_bundle,
        created_at=NOW,
    ).unwrap()
    second = ceremony.rotate(
        version=2,
        passphrase=PASSPHRASE,
        key_destination=second_key,
        backup_destination=second_bundle,
        created_at=NOW,
    ).unwrap()

    assert first.version == 1
    assert second.version == 2
    assert first.key_id != second.key_id
    assert first_key.exists() and first_bundle.exists()
    assert second_key.exists() and second_bundle.exists()
    assert (
        ceremony.recover(
            bundle=first_bundle,
            passphrase=PASSPHRASE,
            destination=tmp_path / "old-key-rehearsal.key",
        )
        .unwrap()
        .key_id
        == first.key_id
    )


def test_content_free_inventory_maps_each_anchor_to_its_key_version(tmp_path):
    ceremony = FamilyAuthenticityKeyCeremony()
    bundles: list[Path] = []
    keys = [b"family authenticity key version one", b"family authenticity key version two"]
    for version, key in enumerate(keys, start=1):
        bundle = tmp_path / f"v{version}.recovery.json"
        ceremony.backup(
            key=key,
            version=version,
            passphrase=PASSPHRASE,
            destination=bundle,
            created_at=NOW,
        ).unwrap()
        bundles.append(bundle)

    private_words = "तुम हमेशा घर लौट सकती हो।"
    film = tmp_path / "age-4.anchor.json"
    inbox = tmp_path / "leaving-home.anchor.json"
    unknown = tmp_path / "unknown.anchor.json"
    film.write_text(
        json.dumps(
            {
                "schema": "anuvritti.render-anchor.v2",
                "key_id": family_key_id(keys[0]),
                "hmac_sha256": "a" * 64,
            }
        )
    )
    inbox.write_text(
        json.dumps(
            {
                "schema": "anuvritti.future-inbox-anchor.v2",
                "key_id": family_key_id(keys[1]),
                "hmac_sha256": "b" * 64,
            }
        )
    )
    unknown.write_text(
        json.dumps(
            {
                "schema": "anuvritti.render-anchor.v2",
                "key_id": "f" * 64,
                "hmac_sha256": "c" * 64,
            }
        )
    )

    inventory = ceremony.inventory(bundles=bundles, anchors=[film, inbox, unknown]).unwrap()

    assert inventory.coverage[0].version == 1
    assert inventory.coverage[0].film_anchors == (film,)
    assert inventory.coverage[0].inbox_anchors == ()
    assert inventory.coverage[1].version == 2
    assert inventory.coverage[1].inbox_anchors == (inbox,)
    assert inventory.uncovered == (unknown,)
    assert private_words not in inventory.to_text()
    assert PASSPHRASE.decode() not in inventory.to_text()


def test_inventory_rejects_duplicate_versions_and_malformed_documents(tmp_path):
    ceremony = FamilyAuthenticityKeyCeremony()
    first = tmp_path / "one.json"
    duplicate = tmp_path / "duplicate.json"
    for destination in (first, duplicate):
        ceremony.backup(
            key=KEY,
            version=1,
            passphrase=PASSPHRASE,
            destination=destination,
            created_at=NOW,
        ).unwrap()
    malformed_anchor = tmp_path / "bad.anchor.json"
    malformed_anchor.write_text('{"schema":"anuvritti.render-anchor.v2"}')

    duplicate_result = ceremony.inventory(bundles=[first, duplicate], anchors=[])
    malformed_result = ceremony.inventory(bundles=[first], anchors=[malformed_anchor])

    assert duplicate_result.unwrap_err().code is ErrorCode.VALIDATION_FAILED
    assert malformed_result.unwrap_err().code is ErrorCode.VALIDATION_FAILED
