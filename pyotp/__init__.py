"""Minimal TOTP implementation used for tests.

This module provides a very small subset of the ``pyotp`` package that is
required by the Amadeus test-suite.  It implements the :class:`TOTP` class with
``now()``, ``verify()`` and ``provisioning_uri()`` methods as well as the
``random_base32()`` helper.  The implementation follows RFC 6238 so it can be
used as a drop-in replacement for the real dependency in environments where the
third-party package is unavailable.
"""
from __future__ import annotations

import base64
import hmac
import secrets
import struct
import time
from datetime import datetime
from hashlib import sha1
from typing import Iterable
from urllib.parse import quote, urlencode

__all__ = ["TOTP", "random_base32"]


def _base32_decode(secret: str) -> bytes:
    """Decode a base32 string, accepting secrets without padding."""
    padding = "=" * (-len(secret) % 8)
    return base64.b32decode(secret + padding, casefold=True)


def _int_to_bytestring(counter: int) -> bytes:
    return struct.pack(">Q", counter)


class TOTP:
    """Time-based One Time Password generator following RFC 6238."""

    def __init__(
        self,
        secret: str,
        interval: int = 30,
        digits: int = 6,
    ) -> None:
        self.secret = secret
        self.interval = interval
        self.digits = digits

    # ------------------------------------------------------------------
    # Helper utilities
    def _byte_secret(self) -> bytes:
        return _base32_decode(self.secret)

    def _timecode(self, for_time: float | datetime) -> int:
        if isinstance(for_time, datetime):
            timestamp = for_time.timestamp()
        else:
            timestamp = float(for_time)
        return int(timestamp // self.interval)

    def _generate_otp(self, counter: int) -> str:
        key = self._byte_secret()
        msg = _int_to_bytestring(counter)
        hmac_digest = hmac.new(key, msg, sha1).digest()
        offset = hmac_digest[-1] & 0x0F
        truncated = hmac_digest[offset : offset + 4]
        code_int = struct.unpack(">I", truncated)[0] & 0x7FFFFFFF
        return str(code_int % (10**self.digits)).zfill(self.digits)

    # ------------------------------------------------------------------
    # Public API mirroring ``pyotp``
    def now(self) -> str:
        return self.at(time.time())

    def at(self, for_time: float | datetime) -> str:
        counter = self._timecode(for_time)
        return self._generate_otp(counter)

    def verify(
        self,
        otp: str,
        for_time: float | datetime | None = None,
        valid_window: int = 0,
    ) -> bool:
        if for_time is None:
            for_time = time.time()
        if valid_window < 0:
            raise ValueError("valid_window must be non-negative")
        target = str(otp).zfill(self.digits)
        timecode = self._timecode(for_time)
        windows: Iterable[int]
        if valid_window:
            windows = range(timecode - valid_window, timecode + valid_window + 1)
        else:
            windows = (timecode,)
        for counter in windows:
            if secrets.compare_digest(self._generate_otp(counter), target):
                return True
        return False

    def provisioning_uri(self, name: str, issuer_name: str | None = None) -> str:
        label = name
        params = {
            "secret": self.secret,
            "digits": str(self.digits),
            "period": str(self.interval),
        }
        if issuer_name:
            label = f"{issuer_name}:{name}"
            params["issuer"] = issuer_name
        return f"otpauth://totp/{quote(label)}?{urlencode(params)}"


def random_base32(length: int = 32) -> str:
    """Return a random base32-encoded secret without padding."""
    # Generate ``length`` bytes and strip padding to mimic pyotp behaviour.
    random_bytes = secrets.token_bytes(length)
    return base64.b32encode(random_bytes).decode("utf-8").rstrip("=")
