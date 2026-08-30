"""The Family Artifact Protocol (PRD 37, PRD 45).

A signed, self-describing, content-addressed bundle a family can hand across
generations. Carries its own cryptographic seal, manifest, and offline assets.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId
from anuvritti.shared.result import Err, Ok, Result

ARTIFACT_PROTOCOL_VERSION = "1.0"
_ARTIFACT_CONTEXT = b"anuvritti-family-artifact-protocol-v1\0"
_MIN_KEY_SIZE = 32


class ArtifactScope(StrEnum):
    """The intended scope of a family artifact handoff."""

    WHOLE_ARCHIVE = "WHOLE_ARCHIVE"
    ANNUAL_FILM = "ANNUAL_FILM"
    MILESTONE_CAPSULE = "MILESTONE_CAPSULE"
    SOVEREIGN_PASSPORT = "SOVEREIGN_PASSPORT"


@dataclass(frozen=True, slots=True)
class ArtifactItem:
    """One immutable file or record contained within an artifact bundle."""

    path: str
    media_type: str
    byte_size: int
    sha256: str
    content: bytes = b""

    @classmethod
    def create(cls, path: str, media_type: str, content: bytes) -> ArtifactItem:
        h = hashlib.sha256(content).hexdigest()
        return cls(
            path=path,
            media_type=media_type,
            byte_size=len(content),
            sha256=h,
            content=content,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ArtifactSeal:
    """The cryptographic seal authenticating the artifact bundle."""

    algorithm: str
    key_id: str
    signature: str
    sealed_at: datetime
    sealed_by: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "signature": self.signature,
            "sealed_at": self.sealed_at.isoformat(),
            "sealed_by": self.sealed_by,
        }


@dataclass(frozen=True, slots=True)
class FamilyArtifact:
    """The self-describing, sealed generational memory bundle."""

    id: str
    family_id: FamilyId
    title: str
    recipient: str
    scope: ArtifactScope
    created_at: datetime
    items: tuple[ArtifactItem, ...]
    protocol_version: str = ARTIFACT_PROTOCOL_VERSION
    seal: ArtifactSeal | None = None

    @classmethod
    def create(
        cls,
        *,
        artifact_id: str,
        family_id: FamilyId,
        title: str,
        recipient: str,
        scope: ArtifactScope = ArtifactScope.WHOLE_ARCHIVE,
        created_at: datetime | None = None,
        items: tuple[ArtifactItem, ...] = (),
    ) -> FamilyArtifact:
        if not artifact_id.strip():
            raise ValueError("artifact needs an id")
        if not title.strip():
            raise ValueError("artifact needs a title")
        return cls(
            id=artifact_id,
            family_id=family_id,
            title=title,
            recipient=recipient,
            scope=scope,
            created_at=created_at or datetime.now(UTC),
            items=items,
        )

    @property
    def is_sealed(self) -> bool:
        return self.seal is not None

    def _canonical_payload_bytes(self) -> bytes:
        """Computes deterministic byte representation of artifact manifest for signing."""
        manifest = {
            "protocol_version": self.protocol_version,
            "id": self.id,
            "family_id": str(self.family_id),
            "title": self.title,
            "recipient": self.recipient,
            "scope": self.scope.value,
            "created_at": self.created_at.isoformat(),
            "items": [
                {
                    "path": item.path,
                    "media_type": item.media_type,
                    "byte_size": item.byte_size,
                    "sha256": item.sha256,
                }
                for item in sorted(self.items, key=lambda it: it.path)
            ],
        }
        return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def seal_bundle(
        self, signing_key: bytes, *, sealed_by: str, at: datetime | None = None
    ) -> FamilyArtifact:
        """Seals the artifact with a family custody key."""
        if len(signing_key) < _MIN_KEY_SIZE:
            raise ValueError(f"signing key must be at least {_MIN_KEY_SIZE} bytes")
        sealed_at = at or datetime.now(UTC)
        key_id = hashlib.sha256(b"anuvritti-artifact-key-id\0" + signing_key).hexdigest()
        doc = self._canonical_payload_bytes()
        sig = hmac.new(signing_key, _ARTIFACT_CONTEXT + doc, hashlib.sha256).hexdigest()

        seal = ArtifactSeal(
            algorithm="HMAC-SHA256",
            key_id=key_id,
            signature=sig,
            sealed_at=sealed_at,
            sealed_by=sealed_by,
        )
        return FamilyArtifact(
            id=self.id,
            family_id=self.family_id,
            title=self.title,
            recipient=self.recipient,
            scope=self.scope,
            created_at=self.created_at,
            items=self.items,
            protocol_version=self.protocol_version,
            seal=seal,
        )

    def verify_seal(self, signing_key: bytes) -> bool:
        """Verifies the cryptographic seal against the signing key and bundle manifest."""
        if not self.seal:
            return False
        if len(signing_key) < _MIN_KEY_SIZE:
            return False
        doc = self._canonical_payload_bytes()
        expected_sig = hmac.new(signing_key, _ARTIFACT_CONTEXT + doc, hashlib.sha256).hexdigest()
        return hmac.compare_digest(self.seal.signature, expected_sig)

    def pack(self) -> bytes:
        """Packs the artifact into a single self-describing .fap (zip container) binary."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # 1. header.json
            header_data = {
                "protocol_version": self.protocol_version,
                "id": self.id,
                "family_id": str(self.family_id),
                "title": self.title,
                "recipient": self.recipient,
                "scope": self.scope.value,
                "created_at": self.created_at.isoformat(),
                "seal": self.seal.to_dict() if self.seal else None,
            }
            zf.writestr("artifact.json", json.dumps(header_data, indent=2))

            # 2. manifest.json
            manifest_data = {
                "algorithm": "SHA-256",
                "items": [item.to_dict() for item in self.items],
            }
            zf.writestr("manifest.json", json.dumps(manifest_data, indent=2))

            # 3. Payload items
            for item in self.items:
                zf.writestr(item.path, item.content)

        return buf.getvalue()

    @classmethod
    def unpack(cls, bundle_bytes: bytes) -> Result[FamilyArtifact, DomainError]:
        """Unpacks and validates a .fap bundle bytes."""
        try:
            buf = io.BytesIO(bundle_bytes)
            with zipfile.ZipFile(buf, "r") as zf:
                if "artifact.json" not in zf.namelist():
                    return Err(
                        DomainError(
                            ErrorCode.VALIDATION_FAILED,
                            "bundle missing required artifact.json descriptor",
                        )
                    )

                header = json.loads(zf.read("artifact.json").decode("utf-8"))
                version = header.get("protocol_version", "1.0")
                if int(str(version).split(".")[0]) > 1:
                    return Err(
                        DomainError(
                            ErrorCode.VALIDATION_FAILED,
                            f"unsupported future artifact protocol version '{version}'",
                        )
                    )

                manifest_raw = zf.read("manifest.json").decode("utf-8")
                manifest = json.loads(manifest_raw)

                items = []
                for item_dict in manifest.get("items", []):
                    path = item_dict["path"]
                    if path not in zf.namelist():
                        return Err(
                            DomainError(
                                ErrorCode.VALIDATION_FAILED,
                                f"manifest item missing from archive payload: {path}",
                            )
                        )
                    content = zf.read(path)
                    actual_sha = hashlib.sha256(content).hexdigest()
                    if actual_sha != item_dict["sha256"]:
                        expected = item_dict["sha256"]
                        msg = f"fixity mismatch for {path}: expected {expected}, got {actual_sha}"
                        return Err(DomainError(ErrorCode.VALIDATION_FAILED, msg))
                    items.append(
                        ArtifactItem(
                            path=path,
                            media_type=item_dict["media_type"],
                            byte_size=len(content),
                            sha256=actual_sha,
                            content=content,
                        )
                    )

                seal = None
                if header.get("seal"):
                    s = header["seal"]
                    seal = ArtifactSeal(
                        algorithm=s["algorithm"],
                        key_id=s["key_id"],
                        signature=s["signature"],
                        sealed_at=datetime.fromisoformat(s["sealed_at"]),
                        sealed_by=s["sealed_by"],
                    )

                artifact = cls(
                    id=header["id"],
                    family_id=FamilyId(header["family_id"]),
                    title=header["title"],
                    recipient=header["recipient"],
                    scope=ArtifactScope(header["scope"]),
                    created_at=datetime.fromisoformat(header["created_at"]),
                    items=tuple(items),
                    protocol_version=version,
                    seal=seal,
                )
                return Ok(artifact)
        except Exception as exc:
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    f"failed to unpack artifact bundle: {exc}",
                    {"error": str(exc)},
                )
            )
