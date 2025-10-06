"""Compatibility shim for legacy settings imports."""
from __future__ import annotations

try:  # Preferred import when running from repository root
    from backend.gateway.app.config import (
        AuthSettings,
        DataSettings,
        EngineSettings,
        RiskSettings,
        SecuritySettings,
        Settings,
        StorageSettings,
        settings,
    )
except ModuleNotFoundError:  # pragma: no cover - supports running from backend/
    from gateway.app.config import (  # type: ignore
        AuthSettings,
        DataSettings,
        EngineSettings,
        RiskSettings,
        SecuritySettings,
        Settings,
        StorageSettings,
        settings,
    )

__all__ = [
    "AuthSettings",
    "DataSettings",
    "EngineSettings",
    "RiskSettings",
    "SecuritySettings",
    "Settings",
    "StorageSettings",
    "settings",
]
