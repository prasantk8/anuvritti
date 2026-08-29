"""Authenticate a portable Future Inbox ledger with the family's offline key."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from anuvritti.adapters.authenticity import family_authentication_tag, validate_family_key
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.result import Err, Ok, Result

_LEDGER_SCHEMA = "anuvritti.future-inbox-provenance.v1"
_ANCHOR_SCHEMA = "anuvritti.future-inbox-anchor.v1"
_ANCHOR_CONTEXT = b"anuvritti-future-inbox-ledger-v1\0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_KINDS = frozenset({"WRITTEN", "RECORDING"})


class FutureInboxLedgerAuthenticator:
    """Create and verify a content-free HMAC receipt beside one portable ledger."""

    def anchor(self, ledger: Path, *, key: bytes, destination: Path) -> Result[Path, DomainError]:
        try:
            validate_family_key(key)
            body, payload = _ledger(ledger)
            anchor = {
                "schema": _ANCHOR_SCHEMA,
                "ledger": ledger.name,
                "message_id": payload["message_id"],
                "ledger_sha256": hashlib.sha256(body).hexdigest(),
                "hmac_sha256": family_authentication_tag(body, key=key, context=_ANCHOR_CONTEXT),
            }
            _atomic_json(destination, anchor)
            return Ok(destination)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "the Future Inbox ledger could not be authenticated",
                    {"ledger": str(ledger), "finding": str(exc)},
                )
            )

    def authenticate(self, ledger: Path, *, key: bytes, anchor: Path) -> Result[None, DomainError]:
        try:
            validate_family_key(key)
            body, ledger_payload = _ledger(ledger)
            anchor_payload = _object(json.loads(anchor.read_text(encoding="utf-8")), "anchor")
            expected = {
                "schema": _ANCHOR_SCHEMA,
                "ledger": ledger.name,
                "message_id": ledger_payload["message_id"],
                "ledger_sha256": hashlib.sha256(body).hexdigest(),
                "hmac_sha256": family_authentication_tag(body, key=key, context=_ANCHOR_CONTEXT),
            }
            if any(
                not isinstance(anchor_payload.get(field), str)
                or not hmac.compare_digest(anchor_payload[field], value)
                for field, value in expected.items()
            ):
                raise ValueError("Future Inbox ledger authentication failed")
            return Ok(None)
        except (KeyError, OSError, TypeError, ValueError):
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    "the Future Inbox ledger is not authentic",
                    {
                        "ledger": str(ledger),
                        "findings": ["Future Inbox ledger authentication failed"],
                    },
                )
            )


def _ledger(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = _object(json.loads(body), "ledger")
    if payload.get("schema") != _LEDGER_SCHEMA:
        raise ValueError(f"ledger schema must be {_LEDGER_SCHEMA}")
    message_id = payload.get("message_id")
    entries = payload.get("entries")
    if not isinstance(message_id, str) or not message_id.strip():
        raise ValueError("ledger message_id is missing")
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise ValueError("ledger must account for exactly one artifact")
    sealed_at = payload.get("sealed_at")
    if not isinstance(sealed_at, str):
        raise ValueError("ledger sealed_at is missing")
    instant = datetime.fromisoformat(sealed_at)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("ledger sealed_at must include a UTC offset")
    entry = entries[0]
    if entry.get("kind") not in _ARTIFACT_KINDS:
        raise ValueError("ledger artifact kind is invalid")
    source_id = entry.get("source_id")
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("ledger artifact source_id is missing")
    digest = entry.get("content_hash")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ValueError("ledger artifact content_hash is not a SHA-256 digest")
    byte_size = entry.get("byte_size")
    if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 1:
        raise ValueError("ledger artifact byte_size must be positive")
    return body, payload


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} is not an object")
    return cast(dict[str, Any], value)


def _atomic_json(destination: Path, payload: dict[str, str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Authenticate a portable Future Inbox ledger")
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path, help="family-held offline key file")
    parser.add_argument("--anchor", type=Path)
    parser.add_argument("--write-anchor", type=Path)
    arguments = parser.parse_args()
    if (arguments.anchor is None) == (arguments.write_anchor is None):
        parser.error("choose exactly one of --anchor or --write-anchor")
    authenticator = FutureInboxLedgerAuthenticator()
    if arguments.write_anchor is not None:
        result = authenticator.anchor(
            arguments.ledger,
            key=arguments.key.read_bytes(),
            destination=arguments.write_anchor,
        )
        if isinstance(result, Err):
            print(result.error.message)
            return 1
        print(f"anchored {arguments.ledger} at {result.value}")
        return 0
    verified = authenticator.authenticate(
        arguments.ledger,
        key=arguments.key.read_bytes(),
        anchor=arguments.anchor,
    )
    if isinstance(verified, Err):
        print(verified.error.message)
        return 1
    print(f"authenticated {arguments.ledger} with the family-held key")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator command
    raise SystemExit(main())
