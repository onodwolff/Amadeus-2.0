"""API routes exposing node management operations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, Security, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_current_user
from ..dependencies import get_session
from ..nautilus_service import svc
from ..schemas.nodes import (
    NodeDetailResponse,
    NodeLaunchRequest,
    NodeLogsResponse,
    NodeResponse,
    NodesListResponse,
)

try:  # pragma: no cover - prefer local backend imports during tests
    from backend.gateway.db.models import ApiKey  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - production installs
    from gateway.db.models import ApiKey  # type: ignore

router = APIRouter(prefix="/nodes", tags=["nodes"])


TRADER_SCOPES = ["trader", "manager"]


@router.get("", response_model=NodesListResponse)
def list_nodes(
    current_user=Security(get_current_user, scopes=TRADER_SCOPES),
) -> NodesListResponse:
    handles = svc.list_nodes()
    return NodesListResponse(nodes=handles)


@router.post("/launch", response_model=NodeResponse, status_code=status.HTTP_201_CREATED)
async def launch_node(
    payload: NodeLaunchRequest,
    current_user=Security(get_current_user, scopes=TRADER_SCOPES),
    db: AsyncSession = Depends(get_session),
) -> NodeResponse:
    launch_data = payload.model_dump(exclude_none=True, by_alias=True)
    node_type = payload.type.lower()
    if node_type == "backtest":
        handle = svc.start_backtest(launch_data)
    elif node_type == "live":
        result = await db.execute(
            select(ApiKey.id).where(ApiKey.user_id == current_user.id)
        )
        if result.first() is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Add an exchange API key before launching live trading.",
            )
        handle = svc.start_live(config=launch_data)
    elif node_type == "sandbox":
        handle = svc.start_sandbox(config=launch_data)
    else:  # pragma: no cover - defensive guard for unexpected types
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Unsupported node type")
    return NodeResponse(node=handle)


@router.post("/{node_id}/stop", response_model=NodeResponse)
def stop_node(
    node_id: str,
    current_user=Security(get_current_user, scopes=TRADER_SCOPES),
) -> NodeResponse:
    handle = svc.stop_node(node_id)
    return NodeResponse(node=handle)


@router.post("/{node_id}/restart", response_model=NodeResponse)
def restart_node(
    node_id: str,
    current_user=Security(get_current_user, scopes=TRADER_SCOPES),
) -> NodeResponse:
    handle = svc.restart_node(node_id)
    return NodeResponse(node=handle)


@router.post("/{node_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_node(
    node_id: str,
    current_user=Security(get_current_user, scopes=TRADER_SCOPES),
) -> Response:
    svc.delete_node(node_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{node_id}", response_model=NodeDetailResponse)
def get_node_detail(
    node_id: str,
    current_user=Security(get_current_user, scopes=TRADER_SCOPES),
) -> NodeDetailResponse:
    payload = svc.node_detail(node_id)
    return NodeDetailResponse.model_validate(payload)


@router.get("/{node_id}/logs", response_class=PlainTextResponse)
def export_node_logs(
    node_id: str,
    current_user=Security(get_current_user, scopes=TRADER_SCOPES),
) -> PlainTextResponse:
    content = svc.export_logs(node_id)
    return PlainTextResponse(content)


@router.get("/{node_id}/logs/entries", response_model=NodeLogsResponse)
def get_node_logs(
    node_id: str,
    current_user=Security(get_current_user, scopes=TRADER_SCOPES),
) -> NodeLogsResponse:
    snapshot = svc.stream_snapshot(node_id)
    logs = snapshot.get("logs", [])
    return NodeLogsResponse.model_validate({"logs": logs})
