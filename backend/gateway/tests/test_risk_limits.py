"""Tests for the risk limits persistence and retrieval logic."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.gateway.db.models import RiskLimit, User, UserRole


class _StubRiskService:
    def __init__(self) -> None:
        self._limits: dict[str, object] = {
            "position_limits": {
                "enabled": False,
                "status": "stale",
                "limits": [],
            },
            "max_loss": {
                "enabled": False,
                "status": "stale",
                "daily": 0.0,
                "weekly": 0.0,
            },
            "trade_locks": {
                "enabled": False,
                "status": "stale",
                "locks": [],
            },
        }

    def risk_limits_snapshot(self) -> dict:
        return {"limits": self._limits}

    def update_risk_limits(self, payload: dict) -> dict:
        self._limits = payload
        return {"limits": payload}

    def risk_snapshot(self) -> dict:  # pragma: no cover - not used but required attribute
        return {}


@pytest.mark.asyncio
async def test_risk_limits_save_and_load(db_session, session_factory, monkeypatch):
    """Risk limits should round-trip between storage and the in-memory snapshot."""

    from backend.gateway.app.routes import risk

    stub_service = _StubRiskService()
    monkeypatch.setattr(risk, "svc", stub_service)

    user = User(
        email="risk@example.com",
        username="risk-user",
        name="Risk Manager",
        pwd_hash="argon2$dummy",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.commit()

    limits_payload = risk.RiskLimitsPayload(
        position_limits=risk.PositionLimitsModule(
            enabled=True,
            status="up_to_date",
            limits=[
                risk.PositionLimitConfig(venue="BINANCE", node="alpha", limit=10_000.0),
            ],
        ),
        max_loss=risk.MaxLossModule(
            enabled=True,
            status="up_to_date",
            daily=2_500.0,
            weekly=10_000.0,
        ),
        trade_locks=risk.TradeLocksModule(
            enabled=False,
            status="up_to_date",
            locks=[
                risk.TradeLockConfig(venue="BINANCE", node="alpha", locked=False),
            ],
        ),
    )

    updated = await risk.update_risk_limits(
        payload=limits_payload,
        session=db_session,
        node_id=None,
    )

    assert updated.limits.max_loss.daily == 2_500.0
    assert updated.limits.position_limits.limits[0].venue == "BINANCE"

    verify_session = session_factory()
    try:
        result = await verify_session.execute(select(RiskLimit))
        record = result.scalar_one()
        assert record.cfg["max_loss"]["daily"] == 2_500.0
    finally:
        await verify_session.close()

    loaded = await risk.get_risk_limits(session=db_session, node_id=None)

    assert loaded.limits.max_loss.weekly == 10_000.0
    assert loaded.limits.trade_locks.locks[0].locked is False
    assert loaded.scope.user_id == str(user.id)
