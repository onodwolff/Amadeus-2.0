"""Authentication flow integration tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import pyotp

from backend.gateway.db.models import AuthSession, UserRole

from .utils import create_user


def _ensure_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_login_and_refresh_flow(app, db_session):
    await create_user(
        db_session,
        email="admin@example.com",
        username="admin",
        password="secret",
        roles=[UserRole.ADMIN.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/login",
            json={"email": "admin@example.com", "password": "secret"},
        )
        assert login_response.status_code == 200
        token_payload = login_response.json()
        assert token_payload["tokenType"] == "bearer"
        assert token_payload["expiresIn"] > 0
        assert token_payload["user"]["isAdmin"] is True
        assert token_payload["user"]["emailVerified"] is False
        assert token_payload["user"]["mfaEnabled"] is False
        assert "refreshToken" not in token_payload

        refresh_cookie = login_response.cookies.get("refreshToken")
        assert refresh_cookie

        access_token = token_payload["accessToken"]

        me_response = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me_response.status_code == 200
        me_payload = me_response.json()
        assert me_payload["email"] == "admin@example.com"
        assert set(me_payload["roles"]) == {UserRole.ADMIN.value}
        assert "gateway.admin" in me_payload["permissions"]
        assert me_payload["emailVerified"] is False
        assert me_payload["mfaEnabled"] is False

        refresh_response = await client.post(
            "/auth/refresh",
            cookies={"refreshToken": refresh_cookie},
        )
        assert refresh_response.status_code == 200
        refreshed = refresh_response.json()
        assert refreshed["accessToken"]
        assert isinstance(refreshed["accessToken"], str)
        assert refreshed["user"]["email"] == "admin@example.com"
        assert refreshed["user"]["emailVerified"] is False
        assert refreshed["user"]["mfaEnabled"] is False
        assert "refreshToken" not in refreshed

        refreshed_cookie = refresh_response.cookies.get("refreshToken")
        assert refreshed_cookie
        assert refreshed_cookie != refresh_cookie

    result = await db_session.execute(select(AuthSession))
    sessions = result.scalars().all()
    assert len(sessions) == 2
    revoked = [session for session in sessions if session.revoked_at is not None]
    assert len(revoked) == 1
    family_ids = {session.family_id for session in sessions}
    assert len(family_ids) == 1

    for session in sessions:
        assert session.absolute_expires_at is not None
        assert session.idle_expires_at is not None


@pytest.mark.asyncio
async def test_login_rejects_invalid_credentials(app, db_session):
    await create_user(
        db_session,
        email="member@example.com",
        username="member",
        password="correct-password",
        roles=[UserRole.MEMBER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/auth/login",
            json={"email": "member@example.com", "password": "wrong"},
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


@pytest.mark.asyncio
async def test_logout_revokes_entire_family(app, db_session):
    await create_user(
        db_session,
        email="viewer@example.com",
        username="viewer",
        password="logout-pass",
        roles=[UserRole.VIEWER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/login",
            json={"email": "viewer@example.com", "password": "logout-pass"},
        )
        refresh_cookie = login_response.cookies.get("refreshToken")
        assert refresh_cookie

        refresh_response = await client.post(
            "/auth/refresh",
            cookies={"refreshToken": refresh_cookie},
        )
        refreshed_cookie = refresh_response.cookies.get("refreshToken")
        assert refreshed_cookie

        logout_response = await client.post(
            "/auth/logout",
            cookies={"refreshToken": refreshed_cookie},
        )
        assert logout_response.status_code == 200
        assert logout_response.json()["detail"] == "Logged out"
        cookie_header = logout_response.headers.get("set-cookie", "")
        assert "refreshToken=" in cookie_header

    result = await db_session.execute(select(AuthSession))
    sessions = result.scalars().all()
    assert len(sessions) == 2
    assert all(session.revoked_at is not None for session in sessions)
    family_ids = {session.family_id for session in sessions}
    assert len(family_ids) == 1


@pytest.mark.asyncio
async def test_refresh_reuse_revokes_new_generation(app, db_session):
    await create_user(
        db_session,
        email="reuse@example.com",
        username="reuse",
        password="reuse-pass",
        roles=[UserRole.MANAGER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/login",
            json={"email": "reuse@example.com", "password": "reuse-pass"},
        )
        assert login_response.status_code == 200
        original_cookie = login_response.cookies.get("refreshToken")
        assert original_cookie

        refresh_response = await client.post(
            "/auth/refresh",
            cookies={"refreshToken": original_cookie},
        )
        assert refresh_response.status_code == 200
        fresh_cookie = refresh_response.cookies.get("refreshToken")
        assert fresh_cookie and fresh_cookie != original_cookie

        reuse_response = await client.post(
            "/auth/refresh",
            cookies={"refreshToken": original_cookie},
        )

        assert reuse_response.status_code == 401
        assert reuse_response.json()["detail"] == "Invalid refresh token"

    result = await db_session.execute(select(AuthSession))
    sessions = result.scalars().all()
    assert len(sessions) == 2
    assert all(session.revoked_at is not None for session in sessions)
    family_ids = {session.family_id for session in sessions}
    assert len(family_ids) == 1


@pytest.mark.asyncio
async def test_refresh_rejects_absolute_timeout(app, db_session):
    await create_user(
        db_session,
        email="absolute@example.com",
        username="absolute",
        password="timeout-pass",
        roles=[UserRole.MEMBER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/login",
            json={"email": "absolute@example.com", "password": "timeout-pass"},
        )
        refresh_cookie = login_response.cookies.get("refreshToken")
        assert refresh_cookie

        result = await db_session.execute(select(AuthSession))
        session = result.scalars().first()
        assert session is not None
        session.absolute_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        await db_session.flush()
        await db_session.commit()

        refresh_response = await client.post(
            "/auth/refresh",
            cookies={"refreshToken": refresh_cookie},
        )

    assert refresh_response.status_code == 401
    assert refresh_response.json()["detail"] == "Session expired"

    await db_session.refresh(session)
    assert session.revoked_at is not None


@pytest.mark.asyncio
async def test_refresh_rejects_idle_timeout(app, db_session):
    await create_user(
        db_session,
        email="idle@example.com",
        username="idle",
        password="idle-pass",
        roles=[UserRole.MEMBER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/login",
            json={"email": "idle@example.com", "password": "idle-pass"},
        )
        refresh_cookie = login_response.cookies.get("refreshToken")
        assert refresh_cookie

        result = await db_session.execute(select(AuthSession))
        session = result.scalars().first()
        assert session is not None
        session.idle_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        await db_session.flush()
        await db_session.commit()

        refresh_response = await client.post(
            "/auth/refresh",
            cookies={"refreshToken": refresh_cookie},
        )

    assert refresh_response.status_code == 401
    assert refresh_response.json()["detail"] == "Session expired due to inactivity"

    await db_session.refresh(session)
    assert session.revoked_at is not None


@pytest.mark.asyncio
async def test_refresh_preserves_absolute_and_resets_idle_deadline(app, db_session):
    await create_user(
        db_session,
        email="idleclock@example.com",
        username="idleclock",
        password="idleclock-pass",
        roles=[UserRole.MEMBER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/login",
            json={"email": "idleclock@example.com", "password": "idleclock-pass"},
        )
        assert login_response.status_code == 200
        refresh_cookie = login_response.cookies.get("refreshToken")
        assert refresh_cookie

        result = await db_session.execute(select(AuthSession))
        original_session = result.scalars().first()
        assert original_session is not None
        original_absolute = _ensure_aware(original_session.absolute_expires_at)
        original_idle = _ensure_aware(original_session.idle_expires_at)
        assert original_absolute is not None
        assert original_idle is not None

        await db_session.commit()

        refresh_response = await client.post(
            "/auth/refresh",
            cookies={"refreshToken": refresh_cookie},
        )
        assert refresh_response.status_code == 200

        refreshed_cookie = refresh_response.cookies.get("refreshToken")
        assert refreshed_cookie and refreshed_cookie != refresh_cookie

    all_sessions = await db_session.execute(select(AuthSession).order_by(AuthSession.id))
    sessions = all_sessions.scalars().all()
    assert len(sessions) == 2

    refreshed_session = max(sessions, key=lambda record: record.id)
    assert refreshed_session.parent_session_id == original_session.id
    assert refreshed_session.absolute_expires_at is not None
    assert refreshed_session.idle_expires_at is not None

    refreshed_absolute = _ensure_aware(refreshed_session.absolute_expires_at)
    refreshed_idle = _ensure_aware(refreshed_session.idle_expires_at)

    assert abs((refreshed_absolute - original_absolute).total_seconds()) < 1

    now = datetime.now(timezone.utc)
    idle_delta = (refreshed_idle - now).total_seconds()
    assert 25 * 60 <= idle_delta <= 30 * 60 + 30

    assert (refreshed_idle - original_idle).total_seconds() >= 0

    await db_session.refresh(original_session)
    assert original_session.revoked_at is not None


@pytest.mark.asyncio
async def test_mfa_setup_enable_and_backup_code_flow(app, db_session):
    user = await create_user(
        db_session,
        email="mfa@example.com",
        username="mfauser",
        password="secret",
        roles=[UserRole.MEMBER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/login",
            json={"email": user.email, "password": "secret"},
        )
        assert login_response.status_code == 200
        access_token = login_response.json()["accessToken"]
        auth_headers = {"Authorization": f"Bearer {access_token}"}

        setup_response = await client.post("/auth/me/mfa/setup", headers=auth_headers)
        assert setup_response.status_code == 200
        setup_payload = setup_response.json()
        secret = setup_payload["secret"]
        assert "otpauthUrl" in setup_payload
        totp = pyotp.TOTP(secret)

        enable_response = await client.post(
            "/auth/me/mfa/enable",
            headers=auth_headers,
            json={"code": totp.now()},
        )
        assert enable_response.status_code == 200
        enable_payload = enable_response.json()
        backup_codes = enable_payload["backupCodes"]
        assert len(backup_codes) == 10
        assert enable_payload["detail"] == "Two-factor authentication enabled"

        mfa_challenge = await client.post(
            "/auth/login",
            json={"email": user.email, "password": "secret"},
        )
        assert mfa_challenge.status_code == 202
        challenge_token = mfa_challenge.json()["challengeToken"]

        failure_response = await client.post(
            "/auth/login/mfa",
            json={"challengeToken": challenge_token, "code": "000000"},
        )
        assert failure_response.status_code == 400

        mfa_challenge = await client.post(
            "/auth/login",
            json={"email": user.email, "password": "secret"},
        )
        assert mfa_challenge.status_code == 202
        challenge_token = mfa_challenge.json()["challengeToken"]

        complete_response = await client.post(
            "/auth/login/mfa",
            json={
                "challengeToken": challenge_token,
                "code": totp.now(),
                "rememberDevice": True,
            },
        )
        assert complete_response.status_code == 200
        token_payload = complete_response.json()
        assert token_payload["user"]["mfaEnabled"] is True
        refresh_cookie = complete_response.cookies.get("refreshToken")
        assert refresh_cookie

        backup_challenge = await client.post(
            "/auth/login",
            json={"email": user.email, "password": "secret"},
        )
        assert backup_challenge.status_code == 202
        backup_token = backup_challenge.json()["challengeToken"]
        backup_login = await client.post(
            "/auth/login/mfa",
            json={"challengeToken": backup_token, "code": backup_codes[0]},
        )
        assert backup_login.status_code == 200

        reuse_challenge = await client.post(
            "/auth/login",
            json={"email": user.email, "password": "secret"},
        )
        assert reuse_challenge.status_code == 202
        reuse_token = reuse_challenge.json()["challengeToken"]
        reuse_attempt = await client.post(
            "/auth/login/mfa",
            json={"challengeToken": reuse_token, "code": backup_codes[0]},
        )
        assert reuse_attempt.status_code == 400

        latest_access_token = token_payload["accessToken"]
        regen_headers = {"Authorization": f"Bearer {latest_access_token}"}
        regen_response = await client.post(
            "/auth/me/mfa/backup-codes",
            headers=regen_headers,
            json={"password": "secret"},
        )
        assert regen_response.status_code == 200
        regen_payload = regen_response.json()
        assert regen_payload["detail"] == "Backup codes regenerated"
        assert len(regen_payload["backupCodes"]) == 10


@pytest.mark.asyncio
async def test_admin_can_disable_mfa_and_revoke_sessions(app, db_session):
    admin = await create_user(
        db_session,
        email="admin2@example.com",
        username="admin2",
        password="secret",
        roles=[UserRole.ADMIN.value],
    )
    secret = pyotp.random_base32()
    user = await create_user(
        db_session,
        email="secure@example.com",
        username="secureuser",
        password="hunter2",
        roles=[UserRole.MEMBER.value],
        mfa_enabled=True,
        mfa_secret=secret,
    )
    totp = pyotp.TOTP(secret)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Login target user with MFA to obtain refresh cookie
        challenge = await client.post(
            "/auth/login",
            json={"email": user.email, "password": "hunter2"},
        )
        assert challenge.status_code == 202
        token = challenge.json()["challengeToken"]
        mfa_login = await client.post(
            "/auth/login/mfa",
            json={"challengeToken": token, "code": totp.now()},
        )
        assert mfa_login.status_code == 200
        refresh_cookie = mfa_login.cookies.get("refreshToken")
        assert refresh_cookie

        # Login admin to call disable endpoint
        admin_login = await client.post(
            "/auth/login",
            json={"email": admin.email, "password": "secret"},
        )
        assert admin_login.status_code == 200
        admin_token = admin_login.json()["accessToken"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        disable_response = await client.post(
            f"/admin/users/{user.id}/mfa/disable",
            headers=admin_headers,
        )
        assert disable_response.status_code == 200
        assert "Two-factor authentication disabled" in disable_response.json()["detail"]

        refresh_attempt = await client.post(
            "/auth/refresh",
            cookies={"refreshToken": refresh_cookie},
        )
        assert refresh_attempt.status_code == 401

    result = await db_session.execute(select(AuthSession).where(AuthSession.user_id == user.id))
    sessions = result.scalars().all()
    assert all(session.revoked_at is not None for session in sessions)
