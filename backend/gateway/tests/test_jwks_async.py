"""Tests ensuring JWKS fetching does not block the event loop."""
from __future__ import annotations

import asyncio
import time

import pytest

from backend.gateway.app.jwks import JWKSClient


@pytest.mark.asyncio
async def test_jwks_fetch_allows_other_coroutines(monkeypatch):
    client = JWKSClient("https://identity.invalid/keys", cache_ttl_seconds=5)
    fetch_delay = 0.3

    def slow_refresh(self: JWKSClient) -> dict[str, dict[str, str]]:
        time.sleep(fetch_delay)
        mapping = {
            "slow": {"kid": "slow", "kty": "RSA", "alg": "RS256"},
        }
        self._cached_keys = mapping
        self._cache_expiry = time.time() + self._cache_ttl_seconds
        return mapping

    monkeypatch.setattr(client, "_refresh_cache", slow_refresh.__get__(client, JWKSClient))

    progress: list[str] = []

    async def fetch_key() -> dict[str, str]:
        key = await client.get_signing_key_async("slow")
        progress.append("key_done")
        return key

    async def background_task() -> None:
        await asyncio.sleep(fetch_delay / 3)
        progress.append("tick")
        await asyncio.sleep(fetch_delay / 3)
        progress.append("tock")

    start = time.perf_counter()
    key_result, _ = await asyncio.gather(fetch_key(), background_task())
    elapsed = time.perf_counter() - start

    assert key_result["kid"] == "slow"
    assert progress[0] == "tick"
    assert progress[1] == "tock"
    assert progress[-1] == "key_done"
    assert elapsed < fetch_delay * 1.5
