"""Utilities for recording audit trail events."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

try:  # pragma: no cover - prefer local backend package in tests
    from backend.gateway.db.models import AuditEvent  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - production installs
    from gateway.db.models import AuditEvent  # type: ignore


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
) -> AuditEvent:
    """Persist a new audit event using the provided SQLAlchemy session."""

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
