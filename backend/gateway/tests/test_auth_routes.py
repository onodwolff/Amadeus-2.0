"""Tests for authentication routes and behaviours."""
from __future__ import annotations

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
