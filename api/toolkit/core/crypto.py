"""AES-256-GCM secret encryption with key IDs for rotation (NFR-SEC-02, SECURITY §7)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class DecryptionError(Exception):
    pass


@dataclass(frozen=True)
class Sealed:
    ciphertext: bytes
    nonce: bytes
    key_id: str


class KeyRing:
    """Holds the primary key (used to encrypt) and older keys (decrypt only)."""

    def __init__(self, keys: dict[str, bytes], primary_id: str) -> None:
        if primary_id not in keys:
            raise ValueError("ENCRYPTION_KEY is not configured")
        for kid, key in keys.items():
            if len(key) != 32:
                raise ValueError(f"key {kid!r} must be 32 bytes")
        self._keys = dict(keys)
        self.primary_id = primary_id

    def encrypt(self, plaintext: str, aad: str) -> Sealed:
        nonce = os.urandom(12)
        ct = AESGCM(self._keys[self.primary_id]).encrypt(nonce, plaintext.encode(), aad.encode())
        return Sealed(ct, nonce, self.primary_id)

    def decrypt(self, sealed: Sealed, aad: str) -> str:
        key = self._keys.get(sealed.key_id)
        if key is None:
            raise DecryptionError(f"unknown key id {sealed.key_id!r}")
        try:
            return AESGCM(key).decrypt(sealed.nonce, sealed.ciphertext, aad.encode()).decode()
        except InvalidTag as exc:
            raise DecryptionError("ciphertext failed authentication") from exc

    def needs_rotation(self, sealed: Sealed) -> bool:
        return sealed.key_id != self.primary_id


_keyring: KeyRing | None = None


def get_keyring() -> KeyRing:
    global _keyring  # noqa: PLW0603 - process-wide cache, reset in tests
    if _keyring is None:
        from toolkit.core.config import get_settings

        s = get_settings()
        _keyring = KeyRing(s.encryption_keys(), s.encryption_key_id)
    return _keyring


def reset_keyring() -> None:
    global _keyring  # noqa: PLW0603
    _keyring = None
