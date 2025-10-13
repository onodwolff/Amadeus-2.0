"""Helpers for issuing and consuming one-time user tokens."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import models as db_models


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenService:
    """Issue and consume single-use tokens associated with a user."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    async def issue(
        self,
        *,
        user: db_models.User,
        purpose: db_models.UserTokenPurpose,
        ttl_seconds: int,
    ) -> Tuple[db_models.UserToken, str]:
        """Create and persist a token for ``user`` with the specified ``purpose``."""

        issued_at = self._now()
        await self._session.execute(
            update(db_models.UserToken)
            .where(
                db_models.UserToken.user_id == user.id,
                db_models.UserToken.purpose == purpose,
                db_models.UserToken.consumed_at.is_(None),
            )
            .values(consumed_at=issued_at)
        )

        token = secrets.token_urlsafe(32)
        token_record = db_models.UserToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=_hash_token(token),
            expires_at=issued_at + timedelta(seconds=int(ttl_seconds)),
        )
        self._session.add(token_record)
        await self._session.flush()
        return token_record, token

    async def consume(
        self,
        *,
        token: str,
        purpose: db_models.UserTokenPurpose,
    ) -> db_models.UserToken | None:
        """Mark ``token`` as consumed and return the associated record if valid."""

        token_hash = _hash_token(token)
        stmt = (
            select(db_models.UserToken)
            .options(selectinload(db_models.UserToken.user))
            .where(
                db_models.UserToken.token_hash == token_hash,
                db_models.UserToken.purpose == purpose,
            )
        )
        result = await self._session.execute(stmt)
        record = result.scalars().first()
        if record is None:
            return None

        now = self._now()
        if record.consumed_at is not None:
            return None
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
            record.expires_at = expires_at
        if expires_at <= now:
            return None

        record.consumed_at = now
        await self._session.flush()
        return record


__all__ = ["TokenService"]
