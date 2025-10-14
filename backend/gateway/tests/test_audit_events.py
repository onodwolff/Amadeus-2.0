from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.gateway.app.audit import record_audit_event
from backend.gateway.db.models import AuditEvent, UserRole

from .utils import create_user


@pytest.mark.asyncio
async def test_login_audit_events_recorded(app, db_session):
    user = await create_user(
        db_session,
        email="audited@example.com",
        username="audited",
        password="super-secret",
        roles=[UserRole.MEMBER.value],
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"user-agent": "pytest-agent"},
    ) as client:
        failure_response = await client.post(
            "/auth/login",
            json={"email": user.email, "password": "wrong"},
        )
        assert failure_response.status_code == 401

        success_response = await client.post(
            "/auth/login",
            json={"email": user.email, "password": "super-secret"},
        )
        assert success_response.status_code == 200

    result = await db_session.execute(
        select(AuditEvent)
        .where(AuditEvent.action == "auth.login")
        .order_by(AuditEvent.id.asc())
    )
    events = result.scalars().all()
    assert len(events) == 2

    failure_event, success_event = events
    assert failure_event.result == "failure"
    assert failure_event.metadata_json["reason"] == "invalid_credentials"
    assert failure_event.metadata_json["email"] == user.email
    assert failure_event.user_agent == "pytest-agent"

    assert success_event.result == "success"
    assert success_event.actor_user_id == user.id
    assert success_event.target_user_id == user.id
    assert success_event.metadata_json["mfa_required"] is False
    assert success_event.metadata_json["mfa_method"] == "password"


@pytest.mark.asyncio
async def test_admin_audit_event_filters(app, db_session):
    admin = await create_user(
        db_session,
        email="audit-admin@example.com",
        username="auditadmin",
        password="password",
        roles=[UserRole.ADMIN.value],
    )
    target = await create_user(
        db_session,
        email="audit-target@example.com",
        username="audittarget",
        password="password",
        roles=[UserRole.MEMBER.value],
    )
    other = await create_user(
        db_session,
        email="audit-other@example.com",
        username="auditother",
        password="password",
        roles=[UserRole.MEMBER.value],
    )

    now = datetime.now(timezone.utc)
    await record_audit_event(
        db_session,
        action="admin.update_user",
        result="success",
        actor_user_id=admin.id,
        target_user_id=target.id,
        occurred_at=now - timedelta(days=1),
        metadata={"updated_fields": ["email"]},
    )
    await record_audit_event(
        db_session,
        action="admin.assign_role",
        result="success",
        actor_user_id=admin.id,
        target_user_id=target.id,
        occurred_at=now - timedelta(hours=6),
        metadata={"role": "member"},
    )
    await record_audit_event(
        db_session,
        action="admin.update_user",
        result="success",
        actor_user_id=admin.id,
        target_user_id=other.id,
        occurred_at=now - timedelta(minutes=5),
        metadata={"updated_fields": ["active"]},
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/login",
            json={"email": admin.email, "password": "password"},
        )
        assert login_response.status_code == 200
        admin_token = login_response.json()["accessToken"]

        action_response = await client.get(
            "/admin/audit-events",
            params={"action": "admin.update_user"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert action_response.status_code == 200
        action_events = action_response.json()
        assert len(action_events) == 2
        assert action_events[0]["action"] == "admin.update_user"
        assert action_events[1]["action"] == "admin.update_user"

        filtered_response = await client.get(
            "/admin/audit-events",
            params={
                "actorUserId": str(admin.id),
                "targetUserId": str(target.id),
                "occurredFrom": (now - timedelta(hours=12)).isoformat(),
                "occurredTo": now.isoformat(),
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert filtered_response.status_code == 200
        filtered_events = filtered_response.json()
        assert len(filtered_events) == 1
        assert filtered_events[0]["action"] == "admin.assign_role"
        assert filtered_events[0]["targetUserId"] == target.id
        assert filtered_events[0]["actorUserId"] == admin.id
