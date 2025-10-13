"""API routes exposing system level information."""

from __future__ import annotations

from fastapi import APIRouter

from ..nautilus_service import svc
from ..schemas.system import CoreInfoResponse, HealthStatusResponse


router = APIRouter(prefix="/system", tags=["system"])


@router.get(
    "/health", response_model=HealthStatusResponse, response_model_exclude_none=True
)
def get_health_status() -> HealthStatusResponse:
    """Return the current health status of the Nautilus integration."""

    payload = svc.health_status()
    return HealthStatusResponse.model_validate(payload)


@router.get(
    "/core/info", response_model=CoreInfoResponse, response_model_exclude_none=True
)
def get_core_info() -> CoreInfoResponse:
    """Return core package availability and adapter diagnostics."""

    payload = svc.core_info()
    return CoreInfoResponse.model_validate(payload)

