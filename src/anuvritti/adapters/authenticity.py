"""The cryptographic primitive shared by family-held offline authenticity receipts."""

from __future__ import annotations

import hashlib
import hmac

MINIMUM_FAMILY_KEY_BYTES = 32


def validate_family_key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) < MINIMUM_FAMILY_KEY_BYTES:
        raise ValueError(f"family key must contain at least {MINIMUM_FAMILY_KEY_BYTES} bytes")


def family_authentication_tag(document: bytes, *, key: bytes, context: bytes) -> str:
    """Authenticate exact portable bytes under a format-specific domain separator."""
    validate_family_key(key)
    return hmac.new(key, context + document, hashlib.sha256).hexdigest()
