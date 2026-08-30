"""TASK-1309: Family Artifact Protocol Verification (PRD 37, PRD 45).

Verifies:
1. Creation, sealing, and cryptographic verification of self-describing family artifact bundles.
2. Binary pack & unpack round-trip fixity across memory items.
3. Tamper detection and rejection of compromised artifact archives.
4. Clean refusal of unsupported future protocol versions.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime

import pytest

from anuvritti.domain.artifact import (
    ArtifactItem,
    ArtifactScope,
    FamilyArtifact,
)
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import FamilyId

TEST_KEY = b"sovereign_family_master_key_32b!"
WRONG_KEY = b"wrong_attacker_attempt_key_32b!!"


@pytest.fixture
def sample_artifact():
    now = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
    item_sparks = ArtifactItem.create(
        path="sparks.json",
        media_type="application/json",
        content=b'[{"id":"spark-1","title":"Walking in garden"}]',
    )
    item_photo = ArtifactItem.create(
        path="media/photo-1.jpg",
        media_type="image/jpeg",
        content=b"JPEG_LEO_FIRST_SUNFLOWER_BYTES",
    )
    item_voice = ArtifactItem.create(
        path="media/voice-1.wav",
        media_type="audio/wav",
        content=b"RIFFWAVE_LEO_BABBLING_AUDIO_BYTES",
    )

    art = FamilyArtifact.create(
        artifact_id="art-leo-eighteen",
        family_id=FamilyId("fam-artifact-01"),
        title="Leo's Milestone Capsule",
        recipient="Leo Singh",
        scope=ArtifactScope.MILESTONE_CAPSULE,
        created_at=now,
        items=(item_sparks, item_photo, item_voice),
    )
    return art.seal_bundle(TEST_KEY, sealed_by="Papa", at=now)


def test_artifact_sealing_and_cryptographic_verification(sample_artifact):
    """Artifact carries a valid cryptographic HMAC-SHA256 seal."""
    assert sample_artifact.is_sealed
    assert sample_artifact.seal is not None
    assert sample_artifact.seal.sealed_by == "Papa"
    assert sample_artifact.seal.algorithm == "HMAC-SHA256"

    # Verifies with true key
    assert sample_artifact.verify_seal(TEST_KEY) is True

    # Refuses wrong key
    assert sample_artifact.verify_seal(WRONG_KEY) is False


def test_artifact_pack_and_unpack_roundtrip(sample_artifact):
    """Packing to .fap bundle and unpacking preserves 100% fixity and seal."""
    packed_bytes = sample_artifact.pack()
    assert len(packed_bytes) > 0

    unpacked_res = FamilyArtifact.unpack(packed_bytes)
    assert unpacked_res.is_ok(), f"Unpack failed: {unpacked_res.unwrap_err()}"
    unpacked = unpacked_res.unwrap()

    assert unpacked.id == sample_artifact.id
    assert unpacked.family_id == sample_artifact.family_id
    assert unpacked.title == sample_artifact.title
    assert unpacked.recipient == sample_artifact.recipient
    assert unpacked.scope == sample_artifact.scope
    assert len(unpacked.items) == 3

    # Cryptographic seal remains authentic after unpack
    assert unpacked.verify_seal(TEST_KEY) is True

    for orig_item, new_item in zip(sample_artifact.items, unpacked.items, strict=True):
        assert new_item.path == orig_item.path
        assert new_item.sha256 == orig_item.sha256
        assert new_item.content == orig_item.content


def test_unpack_detects_tampered_payload(sample_artifact):
    """Any alteration of a byte within the bundle fails integrity checks immediately."""
    packed_bytes = sample_artifact.pack()

    # Tamper with photo-1.jpg inside the zip
    buf_in = io.BytesIO(packed_bytes)
    buf_out = io.BytesIO()
    with zipfile.ZipFile(buf_in, "r") as zin, zipfile.ZipFile(buf_out, "w") as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename == "media/photo-1.jpg":
                content = b"CORRUPTED_TAMPERED_PHOTO_BYTES"
            zout.writestr(item, content)

    tampered_bytes = buf_out.getvalue()
    unpack_res = FamilyArtifact.unpack(tampered_bytes)
    assert unpack_res.is_err()
    err = unpack_res.unwrap_err()
    assert err.code == ErrorCode.VALIDATION_FAILED
    assert "fixity mismatch for media/photo-1.jpg" in err.message


def test_unpack_rejects_unsupported_future_version(sample_artifact):
    """Unsupported future protocol versions (e.g. 2.0) are refused out loud."""
    packed_bytes = sample_artifact.pack()

    buf_in = io.BytesIO(packed_bytes)
    buf_out = io.BytesIO()
    with zipfile.ZipFile(buf_in, "r") as zin, zipfile.ZipFile(buf_out, "w") as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename == "artifact.json":
                meta = json.loads(content.decode("utf-8"))
                meta["protocol_version"] = "99.0"
                content = json.dumps(meta).encode("utf-8")
            zout.writestr(item, content)

    future_bytes = buf_out.getvalue()
    unpack_res = FamilyArtifact.unpack(future_bytes)
    assert unpack_res.is_err()
    err = unpack_res.unwrap_err()
    assert err.code == ErrorCode.VALIDATION_FAILED
    assert "unsupported future artifact protocol version '99.0'" in err.message
