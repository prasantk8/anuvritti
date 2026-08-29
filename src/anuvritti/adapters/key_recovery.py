"""Encrypted recovery and content-free inventory for family authenticity keys."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from anuvritti.adapters.authenticity import family_key_id, validate_family_key
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.result import Err, Ok, Result

_BUNDLE_SCHEMA = "anuvritti.family-authenticity-key-recovery.v1"
_FILM_ANCHOR_SCHEMA = "anuvritti.render-anchor.v2"
_INBOX_ANCHOR_SCHEMA = "anuvritti.future-inbox-anchor.v2"
_AAD_CONTEXT = b"anuvritti-family-authenticity-key-recovery-v1\0"
_MINIMUM_PASSPHRASE_BYTES = 16
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class FamilyKeyVersion:
    version: int
    key_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class KeyCoverage:
    version: int
    key_id: str
    film_anchors: tuple[Path, ...]
    inbox_anchors: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class AuthenticityInventory:
    coverage: tuple[KeyCoverage, ...]
    uncovered: tuple[Path, ...]

    def to_text(self) -> str:
        lines: list[str] = []
        for item in self.coverage:
            lines.append(
                f"key v{item.version} {item.key_id}: "
                f"{len(item.film_anchors)} film, {len(item.inbox_anchors)} Future Inbox"
            )
            lines.extend(f"  film: {path.name}" for path in item.film_anchors)
            lines.extend(f"  inbox: {path.name}" for path in item.inbox_anchors)
        lines.extend(f"uncovered: {path.name}" for path in self.uncovered)
        return "\n".join(lines) + ("\n" if lines else "")


class FamilyAuthenticityKeyCeremony:
    """Create, rehearse and inventory versioned offline family keys."""

    def backup(
        self,
        *,
        key: bytes,
        version: int,
        passphrase: bytes,
        destination: Path,
        created_at: datetime | None = None,
    ) -> Result[FamilyKeyVersion, DomainError]:
        try:
            validate_family_key(key)
            _validate_passphrase(passphrase)
            _validate_version(version)
            instant = created_at or datetime.now(UTC)
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise ValueError("created_at must include a UTC offset")
            public = {
                "schema": _BUNDLE_SCHEMA,
                "key_version": version,
                "key_id": family_key_id(key),
                "created_at": instant.isoformat(),
            }
            salt = os.urandom(16)
            nonce = os.urandom(12)
            encrypted = AESGCM(_derive(passphrase, salt)).encrypt(
                nonce, key, _associated_data(public)
            )
            payload: dict[str, object] = {
                **public,
                "kdf": {
                    "name": "scrypt",
                    "salt": _encode(salt),
                    "n": _SCRYPT_N,
                    "r": _SCRYPT_R,
                    "p": _SCRYPT_P,
                },
                "cipher": {"name": "AES-256-GCM", "nonce": _encode(nonce)},
                "ciphertext": _encode(encrypted),
            }
            _atomic_write(destination, _json_bytes(payload), mode=0o600)
            return Ok(FamilyKeyVersion(version, cast(str, public["key_id"]), instant))
        except (OSError, TypeError, ValueError) as exc:
            return Err(
                _error(ErrorCode.VALIDATION_FAILED, "the family key could not be backed up", exc)
            )

    def recover(
        self, *, bundle: Path, passphrase: bytes, destination: Path
    ) -> Result[FamilyKeyVersion, DomainError]:
        try:
            _validate_passphrase(passphrase)
            payload, version = _recovery_bundle(bundle)
            public = _public_fields(payload)
            key = _decrypt_bundle(payload, passphrase)
            _atomic_write(destination, key, mode=0o600)
            return Ok(FamilyKeyVersion(version, public["key_id"], _instant(public["created_at"])))
        except (InvalidTag, OSError, TypeError, ValueError):
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    "the family key recovery rehearsal failed",
                    {"bundle": str(bundle), "finding": "bundle or passphrase is not authentic"},
                )
            )

    def rotate(
        self,
        *,
        version: int,
        passphrase: bytes,
        key_destination: Path,
        backup_destination: Path,
        created_at: datetime | None = None,
    ) -> Result[FamilyKeyVersion, DomainError]:
        key = os.urandom(32)
        backed_up = self.backup(
            key=key,
            version=version,
            passphrase=passphrase,
            destination=backup_destination,
            created_at=created_at,
        )
        if isinstance(backed_up, Err):
            return backed_up
        try:
            _atomic_write(key_destination, key, mode=0o600)
            return backed_up
        except OSError as exc:
            return Err(
                _error(
                    ErrorCode.VALIDATION_FAILED, "the rotated family key could not be written", exc
                )
            )

    def inventory(
        self, *, bundles: Sequence[Path], anchors: Sequence[Path], passphrase: bytes
    ) -> Result[AuthenticityInventory, DomainError]:
        try:
            _validate_passphrase(passphrase)
            versions: dict[str, tuple[int, list[Path], list[Path]]] = {}
            seen_versions: set[int] = set()
            for bundle in bundles:
                payload, version = _recovery_bundle(bundle)
                key_id = cast(str, payload["key_id"])
                _decrypt_bundle(payload, passphrase)
                if version in seen_versions or key_id in versions:
                    raise ValueError("key versions and identifiers must be unique")
                seen_versions.add(version)
                versions[key_id] = (version, [], [])
            uncovered: list[Path] = []
            for anchor in anchors:
                payload = _object(json.loads(anchor.read_bytes()), "anchor")
                schema = payload.get("schema")
                anchor_key_id = payload.get("key_id")
                if schema not in {_FILM_ANCHOR_SCHEMA, _INBOX_ANCHOR_SCHEMA}:
                    raise ValueError(f"unsupported anchor schema in {anchor.name}")
                if not isinstance(anchor_key_id, str) or _SHA256.fullmatch(anchor_key_id) is None:
                    raise ValueError(f"anchor key_id is invalid in {anchor.name}")
                if anchor_key_id not in versions:
                    uncovered.append(anchor)
                elif schema == _FILM_ANCHOR_SCHEMA:
                    versions[anchor_key_id][1].append(anchor)
                else:
                    versions[anchor_key_id][2].append(anchor)
            coverage = tuple(
                KeyCoverage(version, key_id, tuple(sorted(films)), tuple(sorted(inbox)))
                for key_id, (version, films, inbox) in sorted(
                    versions.items(), key=lambda item: item[1][0]
                )
            )
            return Ok(AuthenticityInventory(coverage, tuple(sorted(uncovered))))
        except (InvalidTag, KeyError, OSError, TypeError, ValueError) as exc:
            return Err(
                _error(ErrorCode.VALIDATION_FAILED, "the key inventory could not be built", exc)
            )


def _recovery_bundle(path: Path) -> tuple[dict[str, Any], int]:
    payload = _object(json.loads(path.read_bytes()), "recovery bundle")
    if payload.get("schema") != _BUNDLE_SCHEMA:
        raise ValueError("recovery bundle schema is invalid")
    version = payload.get("key_version")
    _validate_version(version)
    key_id = payload.get("key_id")
    if not isinstance(key_id, str) or _SHA256.fullmatch(key_id) is None:
        raise ValueError("recovery bundle key_id is invalid")
    _instant(payload.get("created_at"))
    return payload, cast(int, version)


def _public_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {field: payload[field] for field in ("schema", "key_version", "key_id", "created_at")}


def _associated_data(public: dict[str, Any]) -> bytes:
    return _AAD_CONTEXT + json.dumps(public, sort_keys=True, separators=(",", ":")).encode()


def _decrypt_bundle(payload: dict[str, Any], passphrase: bytes) -> bytes:
    public = _public_fields(payload)
    kdf = _object(payload.get("kdf"), "kdf")
    cipher = _object(payload.get("cipher"), "cipher")
    salt = _decode(kdf.get("salt"), "kdf.salt", 16)
    nonce = _decode(cipher.get("nonce"), "cipher.nonce", 12)
    ciphertext = _decode(payload.get("ciphertext"), "ciphertext")
    key = AESGCM(_derive(passphrase, salt)).decrypt(nonce, ciphertext, _associated_data(public))
    validate_family_key(key)
    if family_key_id(key) != public["key_id"]:
        raise InvalidTag
    return key


def _derive(passphrase: bytes, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P).derive(passphrase)


def _validate_passphrase(passphrase: bytes) -> None:
    if not isinstance(passphrase, bytes) or len(passphrase) < _MINIMUM_PASSPHRASE_BYTES:
        raise ValueError(
            f"recovery passphrase must contain at least {_MINIMUM_PASSPHRASE_BYTES} bytes"
        )


def _validate_version(version: object) -> None:
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("key version must be a positive integer")


def _instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("created_at is invalid")
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("created_at must include a UTC offset")
    return instant


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} is not an object")
    return cast(dict[str, Any], value)


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: object, field: str, length: int | None = None) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{field} is invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError(f"{field} is invalid") from exc
    if length is not None and len(decoded) != length:
        raise ValueError(f"{field} is invalid")
    return decoded


def _json_bytes(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def _atomic_write(destination: Path, body: bytes, *, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _error(code: ErrorCode, message: str, exc: BaseException) -> DomainError:
    return DomainError(code, message, {"finding": str(exc)})


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover and inventory family authenticity keys")
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--key", required=True, type=Path)
    backup.add_argument("--version", required=True, type=int)
    backup.add_argument("--passphrase", required=True, type=Path)
    backup.add_argument("--bundle", required=True, type=Path)
    recover = commands.add_parser("recover")
    recover.add_argument("--bundle", required=True, type=Path)
    recover.add_argument("--passphrase", required=True, type=Path)
    recover.add_argument("--key", required=True, type=Path)
    rotate = commands.add_parser("rotate")
    rotate.add_argument("--version", required=True, type=int)
    rotate.add_argument("--passphrase", required=True, type=Path)
    rotate.add_argument("--key", required=True, type=Path)
    rotate.add_argument("--bundle", required=True, type=Path)
    inventory = commands.add_parser("inventory")
    inventory.add_argument("--bundle", action="append", required=True, type=Path)
    inventory.add_argument("--anchor", action="append", default=[], type=Path)
    inventory.add_argument("--passphrase", required=True, type=Path)
    arguments = parser.parse_args()
    ceremony = FamilyAuthenticityKeyCeremony()
    if arguments.command == "inventory":
        inventory_result = ceremony.inventory(
            bundles=arguments.bundle,
            anchors=arguments.anchor,
            passphrase=arguments.passphrase.read_bytes(),
        )
        if isinstance(inventory_result, Err):
            print(inventory_result.error.message)
            return 1
        print(inventory_result.value.to_text(), end="")
        return 0
    if arguments.command == "backup":
        result = ceremony.backup(
            key=arguments.key.read_bytes(),
            version=arguments.version,
            passphrase=arguments.passphrase.read_bytes(),
            destination=arguments.bundle,
        )
    elif arguments.command == "recover":
        result = ceremony.recover(
            bundle=arguments.bundle,
            passphrase=arguments.passphrase.read_bytes(),
            destination=arguments.key,
        )
    elif arguments.command == "rotate":
        result = ceremony.rotate(
            version=arguments.version,
            passphrase=arguments.passphrase.read_bytes(),
            key_destination=arguments.key,
            backup_destination=arguments.bundle,
        )
    else:  # argparse's required choices make this defensive only
        parser.error("unknown key ceremony command")
    if isinstance(result, Err):
        print(result.error.message)
        return 1
    print(f"family authenticity key v{result.value.version}: {result.value.key_id}")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator command
    raise SystemExit(main())
