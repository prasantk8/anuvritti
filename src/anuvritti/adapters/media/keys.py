"""Keyring & Zero-Downtime Envelope Key Rotation (HARDENING 5.5, PRD 44).

Rules:
1. Zero Downtime Rotation: Encryption always uses the current primary active key.
2. Dual-Read Backward Compatibility: Historical media encrypted under retired keys
   decrypts seamlessly without taking the server down or requiring a massive blocking migration.
3. Gradual Re-wrapping: `rotate_payload()` re-encrypts individual items under the
   current active key.
"""

from __future__ import annotations

from collections.abc import Sequence

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class KeyRing:
    """Manages primary active key and historical key rotation via MultiFernet."""

    def __init__(
        self,
        active_key: str,
        historical_keys: Sequence[str] | None = None,
    ) -> None:
        self._active_key = active_key.strip()
        self._historical_keys = [
            k.strip() for k in (historical_keys or []) if k.strip() != self._active_key
        ]
        self._rebuild_cipher()

    def _rebuild_cipher(self) -> None:
        all_keys = [self._active_key, *self._historical_keys]
        fernets = [Fernet(k.encode("utf-8") if isinstance(k, str) else k) for k in all_keys]
        self._multi_fernet = MultiFernet(fernets)
        self._active_fernet = fernets[0]

    @property
    def active_key(self) -> str:
        return self._active_key

    @property
    def historical_keys(self) -> list[str]:
        return list(self._historical_keys)

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt data with the active primary key."""
        return self._active_fernet.encrypt(data)

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt data trying active key first, then historical keys."""
        try:
            return self._multi_fernet.decrypt(ciphertext)
        except InvalidToken as err:
            raise InvalidToken(
                "Ciphertext could not be decrypted with any key in the keyring"
            ) from err

    def rotate_payload(self, ciphertext: bytes) -> bytes:
        """Re-encrypts payload under current active key if it was encrypted with an older key."""
        return self._multi_fernet.rotate(ciphertext)

    def rotate_active_key(self, new_active_key: str) -> None:
        """Promote a new active key; previous active key becomes historical."""
        new_key = new_active_key.strip()
        if new_key == self._active_key:
            return
        if self._active_key not in self._historical_keys:
            self._historical_keys.insert(0, self._active_key)
        self._active_key = new_key
        self._rebuild_cipher()

    def add_historical_key(self, old_key: str) -> None:
        """Add an older historical key to allow decrypting legacy media."""
        key = old_key.strip()
        if key != self._active_key and key not in self._historical_keys:
            self._historical_keys.append(key)
            self._rebuild_cipher()


def create_keyring(keys: str | Sequence[str] | KeyRing) -> KeyRing:
    """Factory helper accepting comma-separated strings, lists, or existing KeyRing."""
    if isinstance(keys, KeyRing):
        return keys
    if isinstance(keys, str):
        parts = [k.strip() for k in keys.split(",") if k.strip()]
        if not parts:
            raise ValueError("At least one encryption key is required")
        return KeyRing(active_key=parts[0], historical_keys=parts[1:])
    if isinstance(keys, (list, tuple)):
        if not keys:
            raise ValueError("At least one encryption key is required")
        return KeyRing(active_key=keys[0], historical_keys=keys[1:])
    raise TypeError(f"Invalid key configuration: {type(keys)}")
