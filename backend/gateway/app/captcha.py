"""Utilities for verifying CAPTCHA challenges."""
from __future__ import annotations

import logging
from typing import Any

import httpx


logger = logging.getLogger(__name__)


class CaptchaVerifier:
    """Verify CAPTCHA tokens against a remote verification endpoint."""

    def __init__(
        self,
        *,
        secret_key: str | None,
        verification_url: str,
        timeout_seconds: float,
        site_key: str | None = None,
        test_bypass_token: str | None = None,
    ) -> None:
        self._secret_key = (secret_key or "").strip()
        self._verification_url = verification_url
        self._timeout_seconds = timeout_seconds
        self._site_key = site_key
        self._test_bypass_token = (test_bypass_token or "").strip() or None

    @property
    def enabled(self) -> bool:
        """Return ``True`` when the verifier has the required credentials."""

        return bool(self._secret_key)

    @property
    def site_key(self) -> str | None:
        return self._site_key

    async def verify(self, token: str | None, remote_ip: str | None = None) -> bool:
        """Validate ``token`` with the configured CAPTCHA provider."""

        if not self.enabled:
            logger.debug("captcha verifier disabled – treating token as invalid")
            return False

        if token is None:
            return False

        cleaned_token = token.strip()
        if not cleaned_token:
            return False

        if self._test_bypass_token and cleaned_token == self._test_bypass_token:
            logger.debug("captcha token matched bypass token")
            return True

        payload: dict[str, Any] = {
            "secret": self._secret_key,
            "response": cleaned_token,
        }
        if remote_ip:
            payload["remoteip"] = remote_ip

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(self._verification_url, data=payload)
            response.raise_for_status()
        except Exception:  # pragma: no cover - network failure logging
            logger.warning("captcha verification request failed", exc_info=True)
            return False

        try:
            body = response.json()
        except ValueError:  # pragma: no cover - defensive parsing
            logger.warning("captcha verification response was not JSON")
            return False

        success = bool(body.get("success"))
        if not success:
            logger.info(
                "captcha verification rejected",
                extra={"errors": body.get("error-codes", [])},
            )
        return success


__all__ = ["CaptchaVerifier"]
