"""Pydantic models for system status endpoints."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from .nodes import AdapterStatus


class AdapterSummary(BaseModel):
    """Aggregate adapter connection statistics."""

    total: int
    connected: int

    model_config = ConfigDict(extra="allow")


class CoreInfoAdapters(AdapterSummary):
    """Detailed adapter information for Nautilus core."""

    items: Optional[List[AdapterStatus]] = None

    model_config = ConfigDict(extra="allow")


class HealthStatusResponse(BaseModel):
    """Response schema for ``GET /system/health``."""

    status: str
    env: str
    adapters: AdapterSummary

    model_config = ConfigDict(extra="allow")


class CoreInfoResponse(BaseModel):
    """Response schema for ``GET /system/core/info``."""

    nautilus_version: str
    available: bool
    adapters: CoreInfoAdapters

    model_config = ConfigDict(extra="allow")

