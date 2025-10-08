"""Security helpers shared across API routers."""
from __future__ import annotations

import hashlib
import hmac
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError

_PASSWORD_HASHER: Final[PasswordHasher] = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""

    return _PASSWORD_HASHER.hash(password)


def verify_password(stored_hash: str, candidate: str) -> bool:
    """Verify a plaintext password against the stored hash."""

    try:
        return _PASSWORD_HASHER.verify(stored_hash, candidate)
    except VerifyMismatchError:
        return False
    except InvalidHash:
        legacy = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        return hmac.compare_digest(stored_hash, legacy)
