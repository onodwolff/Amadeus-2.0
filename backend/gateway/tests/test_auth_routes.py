"""Tests for authentication routes and behaviours."""
from __future__ import annotations

from datetime import datetime, timezone
import sys
from types import SimpleNamespace

from fastapi import FastAPI, status
from fastapi.testclient import TestClient

if "jwt" not in sys.modules:
    sys.modules["jwt"] = SimpleNamespace(
        decode=lambda *args, **kwargs: {},
        ExpiredSignatureError=Exception,
        InvalidTokenError=Exception,
    )

if "pyotp" not in sys.modules:
    sys.modules["pyotp"] = SimpleNamespace(
        TOTP=lambda *args, **kwargs: SimpleNamespace(verify=lambda *a, **k: False)
    )

import backend.gateway as backend_gateway
import backend.gateway.app as backend_gateway_app
import backend.gateway.app.config as backend_gateway_config
import backend.gateway.app.dependencies as backend_app_dependencies
import backend.gateway.app.routes.auth as backend_auth_module
import backend.gateway.app.security as backend_app_security
import backend.gateway.db as backend_gateway_db
import backend.gateway.db.models as backend_db_models

sys.modules.setdefault("gateway", backend_gateway)
sys.modules.setdefault("gateway.app", backend_gateway_app)
sys.modules.setdefault("gateway.app.config", backend_gateway_config)
sys.modules.setdefault("gateway.app.dependencies", backend_app_dependencies)
sys.modules.setdefault("gateway.app.routes.auth", backend_auth_module)
sys.modules.setdefault("gateway.app.security", backend_app_security)
sys.modules.setdefault("gateway.db", backend_gateway_db)
sys.modules.setdefault("gateway.db.models", backend_db_models)

from gateway.app.config import settings
from gateway.app.dependencies import get_session
from gateway.app.state_sync import Base as EngineBase
from gateway.db.base import Base as GatewayBase, metadata as gateway_metadata

auth = backend_auth_module

gateway_metadata.schema = None
for table in gateway_metadata.tables.values():
    table.schema = None

GatewayBase.metadata.schema = None
for table in GatewayBase.metadata.tables.values():
    table.schema = None

backend_db_models.Base.metadata.schema = None
for table in backend_db_models.Base.metadata.tables.values():
    table.schema = None

EngineBase.metadata.schema = None
for table in EngineBase.metadata.tables.values():
    table.schema = None


async def _dummy_session_dependency():
    """Yield a no-op session used to satisfy dependency wiring."""

    class _DummySession:
        async def execute(self, *_args, **_kwargs):  # pragma: no cover - defensive guard
            raise AssertionError("Database should not be queried for invalid tokens")

    yield _DummySession()


def test_tampered_sub_returns_unauthorized(monkeypatch):
    """A token with a non-integer subject should be rejected with 401."""

    monkeypatch.setattr(settings.auth, "enabled", True)

    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    app.dependency_overrides[get_session] = _dummy_session_dependency

    async def _fake_decode_token(_credentials):
        return {"sub": "not-an-integer"}

    monkeypatch.setattr(auth, "_decode_token", _fake_decode_token)

    with TestClient(app) as client:
        response = client.get("/api/me", headers={"Authorization": "Bearer tampered"})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Invalid token"}


def test_suspended_account_cannot_access_authenticated_routes(monkeypatch):
    """Inactive users should receive a 403 when accessing protected endpoints."""

    monkeypatch.setattr(settings.auth, "enabled", True)

    suspended_user = SimpleNamespace(id=123, active=False)

    class _DummyResult:
        def scalars(self):
            return self

        def first(self):
            return suspended_user

    class _SuspendedSession:
        async def execute(self, *_args, **_kwargs):
            return _DummyResult()

    async def _suspended_session_dependency():
        yield _SuspendedSession()

    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    app.dependency_overrides[get_session] = _suspended_session_dependency

    async def _fake_decode_token(_credentials):
        return {"sub": "123"}

    monkeypatch.setattr(auth, "_decode_token", _fake_decode_token)

    with TestClient(app) as client:
        response = client.get(
            "/api/me", headers={"Authorization": "Bearer valid-token"}
        )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json() == {"detail": "Account is suspended"}


def test_active_account_still_accesses_authenticated_routes(monkeypatch):
    """Active users should continue accessing endpoints protected by the guard."""

    monkeypatch.setattr(settings.auth, "enabled", True)

    now = datetime.now(timezone.utc)
    active_user = SimpleNamespace(
        id=321,
        active=True,
        email="active@example.com",
        is_admin=False,
        email_verified=True,
        mfa_enabled=False,
        created_at=now,
        updated_at=now,
        last_login_at=None,
    )

    class _DummyResult:
        def scalars(self):
            return self

        def first(self):
            return active_user

    class _ActiveSession:
        async def execute(self, *_args, **_kwargs):
            return _DummyResult()

    async def _active_session_dependency():
        yield _ActiveSession()

    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    app.dependency_overrides[get_session] = _active_session_dependency

    async def _fake_decode_token(_credentials):
        return {"sub": "321"}

    monkeypatch.setattr(auth, "_decode_token", _fake_decode_token)

    with TestClient(app) as client:
        response = client.get(
            "/api/me", headers={"Authorization": "Bearer valid-token"}
        )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["id"] == str(active_user.id)
    assert payload["email"] == active_user.email
    assert payload["active"] is True
