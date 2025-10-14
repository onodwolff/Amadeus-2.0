"""Rate limiting helpers for authentication endpoints."""
from __future__ import annotations

from dataclasses import dataclass

from .storage import CacheBackend


@dataclass(frozen=True, slots=True)
class BruteForceStatus:
    """Represents the rate limiting status for a login attempt."""

    failures: int
    requires_captcha: bool
    blocked: bool


class BruteForceProtector:
    """Stateful helper that tracks failed authentication attempts."""

    def __init__(
        self,
        *,
        cache: CacheBackend,
        max_attempts: int,
        window_seconds: int,
        captcha_threshold: int,
        captcha_ttl_seconds: int,
        namespace: str = "auth:bf",
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be at least 1")
        if captcha_threshold < 1:
            raise ValueError("captcha_threshold must be at least 1")
        if captcha_ttl_seconds < 1:
            raise ValueError("captcha_ttl_seconds must be at least 1")

        self._cache = cache
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._captcha_threshold = captcha_threshold
        self._captcha_ttl_seconds = captcha_ttl_seconds
        self._namespace = namespace

    def _make_key(self, key_type: str, email: str, ip_address: str) -> str:
        return f"{self._namespace}:{key_type}:{email}:{ip_address}"

    @staticmethod
    def _normalise_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def _normalise_ip(ip_address: str | None) -> str:
        if not ip_address:
            return "unknown"
        cleaned = ip_address.strip()
        return cleaned or "unknown"

    async def _get_count(self, key: str) -> int:
        raw = await self._cache.get(key)
        if raw is None:
            return 0
        try:
            return int(raw.decode("utf-8"))
        except (ValueError, AttributeError):  # pragma: no cover - defensive
            return 0

    async def _increment(self, key: str, ttl_seconds: int) -> int:
        current = await self._get_count(key)
        current += 1
        await self._cache.set(key, str(current).encode("utf-8"), ttl_seconds)
        return current

    async def evaluate(self, *, email: str, ip_address: str | None) -> BruteForceStatus:
        """Return the current rate limit status for ``email`` and ``ip_address``."""

        email_key = self._normalise_email(email)
        ip_key = self._normalise_ip(ip_address)
        attempt_key = self._make_key("attempt", email_key, ip_key)
        captcha_key = self._make_key("captcha", email_key, ip_key)
        attempts = await self._get_count(attempt_key)
        captcha_failures = await self._get_count(captcha_key)
        blocked = attempts >= self._max_attempts
        requires_captcha = captcha_failures >= self._captcha_threshold
        return BruteForceStatus(
            failures=attempts,
            requires_captcha=requires_captcha,
            blocked=blocked,
        )

    async def register_failure(self, *, email: str, ip_address: str | None) -> BruteForceStatus:
        """Record a failed authentication attempt."""

        email_key = self._normalise_email(email)
        ip_key = self._normalise_ip(ip_address)
        attempt_key = self._make_key("attempt", email_key, ip_key)
        captcha_key = self._make_key("captcha", email_key, ip_key)
        attempts = await self._increment(attempt_key, self._window_seconds)
        captcha_failures = await self._increment(captcha_key, self._captcha_ttl_seconds)
        blocked = attempts >= self._max_attempts
        requires_captcha = captcha_failures >= self._captcha_threshold
        return BruteForceStatus(
            failures=attempts,
            requires_captcha=requires_captcha,
            blocked=blocked,
        )

    async def reset(self, *, email: str, ip_address: str | None) -> None:
        """Clear stored counters for a successful authentication."""

        email_key = self._normalise_email(email)
        ip_key = self._normalise_ip(ip_address)
        attempt_key = self._make_key("attempt", email_key, ip_key)
        captcha_key = self._make_key("captcha", email_key, ip_key)
        await self._cache.delete(attempt_key)
        await self._cache.delete(captcha_key)


__all__ = ["BruteForceProtector", "BruteForceStatus"]
