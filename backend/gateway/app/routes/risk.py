"""Risk management API endpoints."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.base import create_session
from gateway.db.models import Node, RiskLimit, User

from ..nautilus_service import svc

LOGGER = logging.getLogger("gateway.api.risk")
router = APIRouter(prefix="/risk", tags=["risk"])


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a request scoped async database session."""

    session = create_session()
    try:
        yield session
    finally:  # pragma: no cover - cleanup
        await session.close()


RiskModuleStatus = Literal["up_to_date", "stale", "syncing", "error"]


class PositionLimitConfig(BaseModel):
    venue: str
    node: str
    limit: float = Field(..., gt=0)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class PositionLimitsModule(BaseModel):
    enabled: bool
    status: RiskModuleStatus
    limits: list[PositionLimitConfig] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class MaxLossModule(BaseModel):
    enabled: bool
    status: RiskModuleStatus
    daily: float = Field(..., ge=0)
    weekly: float = Field(..., ge=0)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TradeLockConfig(BaseModel):
    venue: str
    node: str
    locked: bool
    reason: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TradeLocksModule(BaseModel):
    enabled: bool
    status: RiskModuleStatus
    locks: list[TradeLockConfig] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class RiskLimitsPayload(BaseModel):
    position_limits: PositionLimitsModule
    max_loss: MaxLossModule
    trade_locks: TradeLocksModule

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class RiskLimitScope(BaseModel):
    user_id: str
    node_id: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class RiskLimitsResponse(BaseModel):
    limits: RiskLimitsPayload
    scope: RiskLimitScope

    model_config = ConfigDict(populate_by_name=True)


def _deserialize_limits(payload: Dict[str, Any]) -> RiskLimitsPayload:
    try:
        return RiskLimitsPayload.model_validate(payload)
    except ValidationError as exc:
        LOGGER.warning("risk_limits_deserialisation_failed", extra={"error": str(exc)})
        snapshot = svc.risk_limits_snapshot()
        limits = snapshot.get("limits") or {}
        return RiskLimitsPayload.model_validate(limits)


async def _resolve_primary_user(session: AsyncSession) -> User:
    result = await session.execute(select(User).order_by(User.id.asc()).limit(1))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No user account configured")
    return user


async def _resolve_node_id(session: AsyncSession, node_ref: Optional[str], *, required: bool) -> Optional[int]:
    if not node_ref:
        return None

    candidate = node_ref.strip()
    if not candidate:
        return None

    try:
        node_pk = int(candidate)
    except ValueError:
        node_pk = None
    else:
        record = await session.get(Node, node_pk)
        if record is not None:
            return node_pk
        node_pk = None

    stmt: Select[int] = select(Node.id).where(Node.summary["external_id"].astext == candidate)
    result = await session.execute(stmt)
    resolved = result.scalar_one_or_none()
    if resolved is None and required:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Node not found")
    return resolved


async def _load_risk_limit(
    session: AsyncSession,
    *,
    user_id: int,
    node_id: Optional[int],
) -> RiskLimit | None:
    stmt = select(RiskLimit).where(RiskLimit.user_id == user_id)
    if node_id is None:
        stmt = stmt.where(RiskLimit.node_id.is_(None))
    else:
        stmt = stmt.where(RiskLimit.node_id == node_id)
    result = await session.execute(stmt.limit(1))
    return result.scalars().first()


@router.get("", response_model=dict)
def get_risk_snapshot() -> Dict[str, Any]:
    """Return the latest risk snapshot composed by the service."""

    return svc.risk_snapshot()


@router.get("/limits", response_model=RiskLimitsResponse)
async def get_risk_limits(
    node_id: Optional[str] = Query(default=None, alias="nodeId"),
    session: AsyncSession = Depends(get_session),
) -> RiskLimitsResponse:
    user = await _resolve_primary_user(session)
    resolved_node_id = await _resolve_node_id(session, node_id, required=False)

    record = await _load_risk_limit(session, user_id=user.id, node_id=resolved_node_id)
    scope_node_id: Optional[str] = node_id if resolved_node_id is not None else None

    if record is None and resolved_node_id is not None:
        record = await _load_risk_limit(session, user_id=user.id, node_id=None)
        scope_node_id = None

    if record is None:
        snapshot = svc.risk_limits_snapshot()
        limits_payload = snapshot.get("limits") or {}
        limits = _deserialize_limits(limits_payload)
    else:
        limits = _deserialize_limits(record.cfg)
        svc.update_risk_limits(limits.model_dump())

    return RiskLimitsResponse(
        limits=limits,
        scope=RiskLimitScope(user_id=str(user.id), node_id=scope_node_id),
    )


@router.put("/limits", response_model=RiskLimitsResponse)
async def update_risk_limits(
    payload: RiskLimitsPayload,
    node_id: Optional[str] = Query(default=None, alias="nodeId"),
    session: AsyncSession = Depends(get_session),
) -> RiskLimitsResponse:
    user = await _resolve_primary_user(session)
    resolved_node_id = await _resolve_node_id(session, node_id, required=node_id is not None)

    record = await _load_risk_limit(session, user_id=user.id, node_id=resolved_node_id)
    if record is None:
        record = RiskLimit(user_id=user.id, node_id=resolved_node_id, cfg=payload.model_dump())
        session.add(record)
    else:
        record.cfg = payload.model_dump()
        record.updated_at = datetime.now(timezone.utc)

    await session.commit()

    snapshot = svc.update_risk_limits(payload.model_dump())
    limits_snapshot = snapshot.get("limits") or payload.model_dump()
    limits = _deserialize_limits(limits_snapshot)

    return RiskLimitsResponse(
        limits=limits,
        scope=RiskLimitScope(
            user_id=str(user.id),
            node_id=str(resolved_node_id) if resolved_node_id is not None else None,
        ),
    )
