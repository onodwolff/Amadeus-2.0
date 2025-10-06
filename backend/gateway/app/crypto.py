"""Encryption helpers for securing stored API credentials."""
from __future__ import annotations

import os
from typing import Final, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

__all__ = ["encrypt", "decrypt", "mask_key"]


_NONCE_SIZE: Final[int] = 12
_KEY_SIZE: Final[int] = 32


def _normalise_key(key: bytes) -> bytes:
    if len(key) != _KEY_SIZE:
        raise ValueError("AES-256-GCM requires a 32-byte key")
    return key


def encrypt(
    plaintext: bytes | str,
    *,
    key: bytes,
    associated_data: Optional[bytes] = None,
) -> bytes:
    """Encrypt *plaintext* with AES-256-GCM returning nonce + ciphertext."""

    material = plaintext.encode("utf-8") if isinstance(plaintext, str) else bytes(plaintext)
    nonce = os.urandom(_NONCE_SIZE)
    cipher = AESGCM(_normalise_key(key))
    encrypted = cipher.encrypt(nonce, material, associated_data)
    return nonce + encrypted


def decrypt(
    payload: bytes,
    *,
    key: bytes,
    associated_data: Optional[bytes] = None,
) -> bytes:
    """Decrypt *payload* produced by :func:`encrypt`."""

    if len(payload) <= _NONCE_SIZE:
        raise ValueError("Encrypted payload is too short")
    nonce, ciphertext = payload[:_NONCE_SIZE], payload[_NONCE_SIZE:]
    cipher = AESGCM(_normalise_key(key))
    return cipher.decrypt(nonce, ciphertext, associated_data)


def mask_key(value: str, *, prefix: int = 4, suffix: int = 4) -> str:
    """Return a masked representation of an access key."""

    token = (value or "").strip()
    if not token:
        return ""
    normalized = token.upper()
    if len(normalized) <= prefix + suffix:
        return normalized
    return f"{normalized[:prefix]}…{normalized[-suffix:]}"
