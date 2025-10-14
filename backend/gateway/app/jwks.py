"""Utilities for fetching and caching JSON Web Key Sets (JWKS)."""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from urllib import error, request

import anyio

__all__ = ["JWKSClient", "JWKSFetchError", "JWKSKeyNotFoundError"]


class JWKSFetchError(RuntimeError):
    """Raised when the JWKS endpoint cannot be reached or parsed."""


class JWKSKeyNotFoundError(RuntimeError):
    """Raised when a requested key identifier is not present in the JWKS payload."""


class JWKSClient:
    """Download and cache signing keys from a JWKS endpoint."""

    def __init__(
        self,
        jwks_url: str,
        *,
        cache_ttl_seconds: int = 600,
        request_timeout: float = 5.0,
    ) -> None:
        if not jwks_url:
            raise ValueError("JWKS URL must be provided")
        self._jwks_url = jwks_url
        self._cache_ttl_seconds = max(cache_ttl_seconds, 1)
        self._request_timeout = max(request_timeout, 0.1)
        self._lock = threading.Lock()
        self._cached_keys: dict[str, dict[str, Any]] | None = None
        self._cache_expiry: float = 0.0

    def _refresh_cache(self) -> dict[str, dict[str, Any]]:
        """Fetch the latest JWKS payload from the identity provider."""

        req = request.Request(self._jwks_url, headers={"Accept": "application/json"})
        try:
            with request.urlopen(req, timeout=self._request_timeout) as response:
                status_code = getattr(response, "status", response.getcode())
                if status_code != 200:
                    raise JWKSFetchError(f"Unexpected JWKS status code: {status_code}")
                payload = response.read()
        except error.URLError as exc:  # pragma: no cover - network failures depend on runtime
            raise JWKSFetchError("Unable to fetch JWKS payload") from exc

        try:
            data = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise JWKSFetchError("JWKS response is not valid JSON") from exc

        keys = data.get("keys")
        if not isinstance(keys, list) or not keys:
            raise JWKSFetchError("JWKS payload does not contain signing keys")

        mapping: dict[str, dict[str, Any]] = {}
        for entry in keys:
            if not isinstance(entry, dict):
                continue
            kid = entry.get("kid")
            if not isinstance(kid, str) or not kid:
                continue
            mapping[kid] = entry

        if not mapping:
            raise JWKSFetchError("No usable signing keys were found in the JWKS payload")

        now = time.time()
        self._cached_keys = mapping
        self._cache_expiry = now + self._cache_ttl_seconds
        return mapping

    async def _refresh_cache_async(self) -> dict[str, dict[str, Any]]:
        """Async wrapper for :meth:`_refresh_cache` executed in a worker thread."""

        return await anyio.to_thread.run_sync(self._refresh_cache)

    def _get_cached_keys(self, *, force_refresh: bool = False) -> dict[str, dict[str, Any]]:
        with self._lock:
            now = time.time()
            if (
                force_refresh
                or self._cached_keys is None
                or now >= self._cache_expiry
            ):
                return self._refresh_cache()
            return self._cached_keys

    async def _get_cached_keys_async(
        self, *, force_refresh: bool = False
    ) -> dict[str, dict[str, Any]]:
        """Async wrapper for :meth:`_get_cached_keys` to avoid blocking the event loop."""

        return await anyio.to_thread.run_sync(
            lambda: self._get_cached_keys(force_refresh=force_refresh)
        )

    def get_signing_key(self, kid: str) -> dict[str, Any]:
        """Return the JWK entry matching ``kid``.

        The JWKS cache is refreshed on expiry or when the requested ``kid``
        is not present in the cached payload.
        """

        if not kid:
            raise JWKSKeyNotFoundError("Key identifier (kid) must be provided")

        keys = self._get_cached_keys()
        key = keys.get(kid)
        if key is not None:
            return key

        keys = self._get_cached_keys(force_refresh=True)
        key = keys.get(kid)
        if key is None:
            raise JWKSKeyNotFoundError(f"Signing key with kid '{kid}' was not found")
        return key

    async def get_signing_key_async(self, kid: str) -> dict[str, Any]:
        """Async wrapper around :meth:`get_signing_key` to prevent event loop blocking."""

        if not kid:
            raise JWKSKeyNotFoundError("Key identifier (kid) must be provided")

        keys = await self._get_cached_keys_async()
        key = keys.get(kid)
        if key is not None:
            return key

        keys = await self._get_cached_keys_async(force_refresh=True)
        key = keys.get(kid)
        if key is None:
            raise JWKSKeyNotFoundError(f"Signing key with kid '{kid}' was not found")
        return key

