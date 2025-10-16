"""Authentication flow integration tests."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import pyotp
from fastapi import Response

from backend.gateway.app.security import TokenData, hash_refresh_token
from backend.gateway.app.routes.auth import _issue_tokens
from backend.gateway.config import settings
from backend.gateway.db.models import AuditEvent, AuthSession, UserRole

from .utils import create_user


def _ensure_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


COOKIE_NAME = settings.auth.refresh_cookie_name


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
        assert COOKIE_NAME not in token_payload

        refresh_cookie = login_response.cookies.get(COOKIE_NAME)
        assert refresh_cookie
        login_cookie_header = login_response.headers.get("set-cookie")
        assert login_cookie_header is not None
        assert f"{COOKIE_NAME}=" in login_cookie_header
        assert "Path=/api/auth" in login_cookie_header
        assert "HttpOnly" in login_cookie_header
        assert "Domain=" not in login_cookie_header
        same_site_value = "none" if settings.auth.cookie_secure else "lax"
        assert f"samesite={same_site_value}" in login_cookie_header.lower()
        if settings.auth.cookie_secure:
            assert "secure" in login_cookie_header.lower()

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
            cookies={COOKIE_NAME: refresh_cookie},
        )
        assert refresh_response.status_code == 200
        refreshed = refresh_response.json()
        assert refreshed["accessToken"]
        assert isinstance(refreshed["accessToken"], str)
        assert refreshed["user"]["email"] == "admin@example.com"
        assert refreshed["user"]["emailVerified"] is False
        assert refreshed["user"]["mfaEnabled"] is False
        assert COOKIE_NAME not in refreshed

        refreshed_cookie = refresh_response.cookies.get(COOKIE_NAME)
        assert refreshed_cookie
        assert refreshed_cookie != refresh_cookie
        refresh_cookie_header = refresh_response.headers.get("set-cookie")
        assert refresh_cookie_header is not None
        assert f"{COOKIE_NAME}=" in refresh_cookie_header
        assert "Path=/api/auth" in refresh_cookie_header
        assert "HttpOnly" in refresh_cookie_header
        assert "Domain=" not in refresh_cookie_header
        assert f"samesite={same_site_value}" in refresh_cookie_header.lower()
        if settings.auth.cookie_secure:
            assert "secure" in refresh_cookie_header.lower()

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


@pytest.fixture
def configure_idp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.auth, "idp_jwks_url", "https://idp.example.com/jwks")
    monkeypatch.setattr(settings.auth, "idp_issuer", "https://idp.example.com")
    monkeypatch.setattr(settings.auth, "idp_audience", "gateway-api")
    monkeypatch.setattr(settings.auth, "idp_token_url", "https://idp.example.com/token")
    monkeypatch.setattr(settings.auth, "idp_client_id", "gateway-client")
    monkeypatch.setattr(settings.auth, "idp_client_secret", "super-secret")
    monkeypatch.setattr(settings.auth, "idp_redirect_uri", "https://app.example.com/callback")
    monkeypatch.setattr(settings.auth, "allow_test_tokens", False)


@pytest.fixture
def idp_token_validation(monkeypatch: pytest.MonkeyPatch) -> TokenData:
    token_data = TokenData(
        subject="42",
        issuer="https://idp.example.com",
        audience=("gateway-api",),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        roles=(),
        scopes=("openid",),
        claims={"email": "oidc@example.com", "email_verified": True, "nonce": "expected-nonce"},
    )

    async def _fake_validate(token: str) -> TokenData:
        assert token == "idp-id-token"
        return token_data

    monkeypatch.setattr(
        "backend.gateway.app.routes.auth.validate_bearer_token_async",
        _fake_validate,
    )
    return token_data


@pytest.fixture
def idp_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyResponse:
        def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
            self._payload = payload
            self.status_code = status_code
            self.text = json.dumps(payload)

        def json(self) -> dict[str, object]:
            return self._payload

    class DummyAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "DummyAsyncClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, data=None, headers=None):  # type: ignore[override]
            grant_type = (data or {}).get("grant_type")
            if grant_type == "authorization_code":
                assert data["client_id"] == "gateway-client"
                assert data["client_secret"] == "super-secret"
                assert data["code"] == "auth-code"
                return DummyResponse(
                    {
                        "id_token": "idp-id-token",
                        "access_token": "idp-access-token-1",
                        "refresh_token": "idp-refresh-token-1",
                        "expires_in": 120,
                        "token_type": "bearer",
                    }
                )
            if grant_type == "refresh_token":
                assert data["refresh_token"] == "idp-refresh-token-1"
                assert data["client_id"] == "gateway-client"
                assert data["client_secret"] == "super-secret"
                return DummyResponse(
                    {
                        "access_token": "idp-access-token-2",
                        "refresh_token": "idp-refresh-token-2",
                        "expires_in": 180,
                        "token_type": "bearer",
                    }
                )
            raise AssertionError(f"Unexpected grant_type: {grant_type}")

    monkeypatch.setattr(
        "backend.gateway.app.routes.auth.httpx.AsyncClient",
        DummyAsyncClient,
    )


@pytest.mark.asyncio
async def test_oidc_login_and_refresh_flow(
    configure_idp,
    idp_token_validation,
    idp_http_client,
    app,
    db_session,
):
    await create_user(
        db_session,
        email="oidc@example.com",
        username="oidc",
        password="irrelevant",
        roles=[UserRole.MEMBER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/auth/oidc/callback",
            json={
                "code": "auth-code",
                "codeVerifier": "v" * 64,
                "redirectUri": "https://app.example.com/callback",
                "nonce": "expected-nonce",
                "state": "login/complete",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["accessToken"] == "idp-access-token-1"
        assert payload["expiresIn"] == 120
        assert payload["user"]["email"] == "oidc@example.com"
        assert payload["user"]["emailVerified"] is True
        assert payload["user"]["mfaEnabled"] is False
        login_cookie = response.cookies.get(COOKIE_NAME)
        assert login_cookie == "idp-refresh-token-1"

        refresh_response = await client.post(
            "/auth/refresh",
            cookies={COOKIE_NAME: login_cookie},
        )

    assert refresh_response.status_code == 200
    refreshed_payload = refresh_response.json()
    assert refreshed_payload["accessToken"] == "idp-access-token-2"
    assert refreshed_payload["expiresIn"] == 180
    assert refreshed_payload["user"]["email"] == "oidc@example.com"
    assert refreshed_payload["user"]["emailVerified"] is True
    assert refreshed_payload["user"]["mfaEnabled"] is False
    rotated_cookie = refresh_response.cookies.get(COOKIE_NAME)
    assert rotated_cookie == "idp-refresh-token-2"

    result = await db_session.execute(select(AuthSession).order_by(AuthSession.id))
    sessions = result.scalars().all()
    assert len(sessions) == 2
    first_session, second_session = sessions
    assert first_session.revoked_at is not None
    assert second_session.parent_session_id == first_session.id
    assert first_session.refresh_token_hash == hash_refresh_token("idp-refresh-token-1")
    assert second_session.refresh_token_hash == hash_refresh_token("idp-refresh-token-2")


@pytest.mark.asyncio
async def test_oidc_login_rejected_on_nonce_mismatch(
    configure_idp,
    idp_token_validation,
    idp_http_client,
    app,
    db_session,
):
    idp_token_validation.claims["nonce"] = "server-nonce"

    await create_user(
        db_session,
        email="oidc@example.com",
        username="oidc",
        password="irrelevant",
        roles=[UserRole.MEMBER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/auth/oidc/callback",
            json={
                "code": "auth-code",
                "codeVerifier": "v" * 64,
                "redirectUri": "https://app.example.com/callback",
                "nonce": "expected-nonce",
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Nonce mismatch"

    result = await db_session.execute(select(AuditEvent).order_by(AuditEvent.id))
    events = result.scalars().all()
    assert any(
        event.action == "auth.login_oidc"
        and event.result == "failure"
        and event.metadata_json.get("reason") == "nonce_mismatch"
        for event in events
    )


@pytest.mark.asyncio
async def test_oidc_refresh_allows_non_rotating_tokens(
    configure_idp,
    idp_token_validation,
    app,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
):
    class DummyResponse:
        def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
            self._payload = payload
            self.status_code = status_code
            self.text = json.dumps(payload)

        def json(self) -> dict[str, object]:
            return self._payload

    class DummyAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "DummyAsyncClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, data=None, headers=None):  # type: ignore[override]
            grant_type = (data or {}).get("grant_type")
            if grant_type == "authorization_code":
                return DummyResponse(
                    {
                        "id_token": "idp-id-token",
                        "access_token": "idp-access-token-initial",
                        "refresh_token": "idp-refresh-token-static",
                        "expires_in": 120,
                        "refresh_expires_in": 7200,
                        "token_type": "bearer",
                    }
                )
            if grant_type == "refresh_token":
                assert data["refresh_token"] == "idp-refresh-token-static"
                return DummyResponse(
                    {
                        "access_token": "idp-access-token-updated",
                        "refresh_token": "idp-refresh-token-static",
                        "expires_in": 300,
                        "refresh_expires_in": 7100,
                        "token_type": "bearer",
                    }
                )
            raise AssertionError(f"Unexpected grant_type: {grant_type}")

    monkeypatch.setattr(
        "backend.gateway.app.routes.auth.httpx.AsyncClient",
        DummyAsyncClient,
    )

    await create_user(
        db_session,
        email="oidc@example.com",
        username="oidc-static",
        password="irrelevant",
        roles=[UserRole.MEMBER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/oidc/callback",
            json={
                "code": "auth-code",
                "codeVerifier": "v" * 64,
                "redirectUri": "https://app.example.com/callback",
            },
        )
        assert login_response.status_code == 200
        login_cookie = login_response.cookies.get(COOKIE_NAME)
        assert login_cookie == "idp-refresh-token-static"

        initial_session_result = await db_session.execute(select(AuthSession))
        initial_session = initial_session_result.scalars().first()
        assert initial_session is not None
        initial_expires_at = _ensure_aware(initial_session.expires_at)

        refresh_response = await client.post(
            "/auth/refresh",
            cookies={COOKIE_NAME: login_cookie},
        )
        assert refresh_response.status_code == 200
        refreshed_cookie = refresh_response.cookies.get(COOKIE_NAME)
        assert refreshed_cookie == "idp-refresh-token-static"
        refreshed_payload = refresh_response.json()
        assert refreshed_payload["accessToken"] == "idp-access-token-updated"
        assert refreshed_payload["expiresIn"] == 300

    result = await db_session.execute(select(AuthSession))
    sessions = result.scalars().all()
    assert len(sessions) == 1
    session = sessions[0]
    assert session.revoked_at is None
    assert session.refresh_token_hash == hash_refresh_token("idp-refresh-token-static")
    updated_expires_at = _ensure_aware(session.expires_at)
    assert updated_expires_at != initial_expires_at
    remaining_seconds = (updated_expires_at - datetime.now(timezone.utc)).total_seconds()
    assert 6800 <= remaining_seconds <= 7205


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
        refresh_cookie = login_response.cookies.get(COOKIE_NAME)
        assert refresh_cookie

        refresh_response = await client.post(
            "/auth/refresh",
            cookies={COOKIE_NAME: refresh_cookie},
        )
        refreshed_cookie = refresh_response.cookies.get(COOKIE_NAME)
        assert refreshed_cookie

        logout_response = await client.post(
            "/auth/logout",
            cookies={COOKIE_NAME: refreshed_cookie},
        )
        assert logout_response.status_code == 200
        assert logout_response.json()["detail"] == "Logged out"
        cookie_header = logout_response.headers.get("set-cookie", "")
        assert f"{COOKIE_NAME}=" in cookie_header

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
        original_cookie = login_response.cookies.get(COOKIE_NAME)
        assert original_cookie

        refresh_response = await client.post(
            "/auth/refresh",
            cookies={COOKIE_NAME: original_cookie},
        )
        assert refresh_response.status_code == 200
        fresh_cookie = refresh_response.cookies.get(COOKIE_NAME)
        assert fresh_cookie and fresh_cookie != original_cookie

        reuse_response = await client.post(
            "/auth/refresh",
            cookies={COOKIE_NAME: original_cookie},
        )

        assert reuse_response.status_code == 401
        assert reuse_response.json()["detail"] == "Invalid refresh token"
        cookie_header = reuse_response.headers.get("set-cookie", "")
        assert f"{COOKIE_NAME}=" in cookie_header
        assert "Max-Age=0" in cookie_header

    result = await db_session.execute(select(AuthSession))
    sessions = result.scalars().all()
    assert len(sessions) == 2
    assert all(session.revoked_at is not None for session in sessions)
    family_ids = {session.family_id for session in sessions}
    assert len(family_ids) == 1


@pytest.mark.asyncio
async def test_issue_tokens_cookie_respects_refresh_expiry(db_session):
    user = await create_user(
        db_session,
        email="expiry-cookie@example.com",
        username="expiry-cookie",
        password="temporary-pass",
        roles=[UserRole.MEMBER.value],
    )

    response = Response()
    issued_at = datetime.now(timezone.utc)
    refresh_expiry = issued_at + timedelta(minutes=5)
    refresh_token_value = f"explicit-refresh-{uuid.uuid4()}"

    token = await _issue_tokens(
        db_session,
        user=user,
        response=response,
        request=None,
        issued_access_token="static-access-token",
        access_token_expires_in=60,
        issued_refresh_token=refresh_token_value,
        refresh_token_expires_at=refresh_expiry,
    )

    completed_at = datetime.now(timezone.utc)

    assert token.refresh_expires_at == refresh_expiry

    cookie_header = response.headers.get("set-cookie", "")
    assert f"{COOKIE_NAME}=" in cookie_header

    max_age_value: int | None = None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.lower().startswith("max-age="):
            max_age_value = int(part.split("=", 1)[1])
            break

    assert max_age_value is not None

    expected_max = max(0, int((refresh_expiry - issued_at).total_seconds()))
    expected_min = max(0, int((refresh_expiry - completed_at).total_seconds()))

    assert expected_min <= max_age_value <= expected_max


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
        refresh_cookie = login_response.cookies.get(COOKIE_NAME)
        assert refresh_cookie

        result = await db_session.execute(select(AuthSession))
        session = result.scalars().first()
        assert session is not None
        session.absolute_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        await db_session.flush()
        await db_session.commit()

        refresh_response = await client.post(
            "/auth/refresh",
            cookies={COOKIE_NAME: refresh_cookie},
        )

    assert refresh_response.status_code == 401
    assert refresh_response.json()["detail"] == "Session expired"
    cookie_header = refresh_response.headers.get("set-cookie", "")
    assert f"{COOKIE_NAME}=" in cookie_header
    assert "Max-Age=0" in cookie_header

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
        refresh_cookie = login_response.cookies.get(COOKIE_NAME)
        assert refresh_cookie

        result = await db_session.execute(select(AuthSession))
        session = result.scalars().first()
        assert session is not None
        session.idle_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        await db_session.flush()
        await db_session.commit()

        refresh_response = await client.post(
            "/auth/refresh",
            cookies={COOKIE_NAME: refresh_cookie},
        )

    assert refresh_response.status_code == 401
    assert refresh_response.json()["detail"] == "Session expired due to inactivity"
    cookie_header = refresh_response.headers.get("set-cookie", "")
    assert f"{COOKIE_NAME}=" in cookie_header
    assert "Max-Age=0" in cookie_header

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
        refresh_cookie = login_response.cookies.get(COOKIE_NAME)
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
            cookies={COOKIE_NAME: refresh_cookie},
        )
        assert refresh_response.status_code == 200

        refreshed_cookie = refresh_response.cookies.get(COOKIE_NAME)
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
        refresh_cookie = complete_response.cookies.get(COOKIE_NAME)
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
        refresh_cookie = mfa_login.cookies.get(COOKIE_NAME)
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
            cookies={COOKIE_NAME: refresh_cookie},
        )
        assert refresh_attempt.status_code == 401
        cookie_header = refresh_attempt.headers.get("set-cookie", "")
        assert f"{COOKIE_NAME}=" in cookie_header
        assert "Max-Age=0" in cookie_header

    result = await db_session.execute(select(AuthSession).where(AuthSession.user_id == user.id))
    sessions = result.scalars().all()
    assert all(session.revoked_at is not None for session in sessions)
