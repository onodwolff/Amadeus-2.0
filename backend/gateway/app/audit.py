"""Utilities for recording audit trail events."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

try:  # pragma: no cover - prefer local backend package in tests
    from backend.gateway.db.models import AuditEvent  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - production installs
    from gateway.db.models import AuditEvent  # type: ignore

from .logging import get_logger


logger = get_logger("gateway.audit")
_audit_table_exists: bool | None = None


async def _ensure_audit_table(session: AsyncSession) -> bool:
    """Return ``True`` when the audit events table is available."""

    global _audit_table_exists

    if _audit_table_exists is True:
        return True
    if _audit_table_exists is False:
        return False

    try:
        exists = await session.run_sync(
            lambda sync_session: inspect(sync_session.connection()).has_table(
                AuditEvent.__table__.name,
                schema=AuditEvent.__table__.schema,
            )
        )
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard
        logger.warning(
            "audit_event_table_check_failed",
            error=str(exc),
        )
        _audit_table_exists = False
        return False

    _audit_table_exists = bool(exists)
    if not exists:
        logger.warning("audit_event_table_missing")
        return False

    return True


async def record_audit_event(
    session: AsyncSession,
    *,
    action: str,
    result: str,
    actor_user_id: int | None = None,
    target_user_id: int | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> AuditEvent | None:
    """Persist a new audit event using the provided SQLAlchemy session.

    Returns the created :class:`AuditEvent` or ``None`` when the audit table is
    unavailable so the caller can continue using the current transaction.
    """

    if not await _ensure_audit_table(session):
        return None

    event = AuditEvent(
        action=action,
        result=result,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        metadata_json=dict(metadata or {}),
    )
    session.add(event)
    await session.flush()
    return event
