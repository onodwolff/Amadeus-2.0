"""Simple helper for dispatching transactional e-mails."""
from __future__ import annotations

import logging
from datetime import datetime
from .config import settings

logger = logging.getLogger(__name__)


class EmailDispatcher:
    """Send password reset and verification links to end users."""

    def __init__(self) -> None:
        self._config = settings.auth

    def _build_url(self, path: str, token: str) -> str:
        base = self._config.public_base_url.rstrip("/")
        suffix = path if path.startswith("/") else f"/{path}"
        return f"{base}{suffix}?token={token}"

    def password_reset_url(self, token: str) -> str:
        return self._build_url(self._config.password_reset_path, token)

    def email_verification_url(self, token: str) -> str:
        return self._build_url(self._config.email_verification_path, token)

    async def send_password_reset_email(
        self,
        *,
        email: str,
        token: str,
        expires_at: datetime,
    ) -> None:
        """Send a password reset link for the supplied ``token``."""

        url = self.password_reset_url(token)
        logger.info(
            "Dispatching password reset email",
            extra={
                "email": email,
                "expires_at": expires_at.isoformat(),
                "url": url,
                "ttl_seconds": self._config.password_reset_token_ttl_seconds,
            },
        )

    async def send_email_verification(
        self,
        *,
        email: str,
        token: str,
        expires_at: datetime,
    ) -> None:
        """Send an email verification link for the supplied ``token``."""

        url = self.email_verification_url(token)
        logger.info(
            "Dispatching email verification",
            extra={
                "email": email,
                "expires_at": expires_at.isoformat(),
                "url": url,
                "ttl_seconds": self._config.email_verification_token_ttl_seconds,
            },
        )


__all__ = ["EmailDispatcher"]
