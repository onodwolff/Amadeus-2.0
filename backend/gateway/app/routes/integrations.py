"""Routes exposing integration metadata."""
from __future__ import annotations

from fastapi import APIRouter

from ..nautilus_service import svc

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/exchanges")
def list_exchanges() -> dict:
    """Return the catalog of available exchange integrations."""

    return svc.list_available_exchanges()
