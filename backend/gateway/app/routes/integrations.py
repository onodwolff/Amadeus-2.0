"""Routes exposing integration metadata."""
from __future__ import annotations

from fastapi import APIRouter, Security

from ..dependencies import get_current_user
from ..nautilus_service import svc

router = APIRouter(prefix="/integrations", tags=["integrations"])


VIEWER_SCOPES = ["viewer", "trader", "manager"]


@router.get("/exchanges")
def list_exchanges(
    current_user=Security(get_current_user, scopes=VIEWER_SCOPES),
) -> dict:
    """Return the catalog of available exchange integrations."""

    return svc.list_available_exchanges()
