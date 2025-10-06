from __future__ import annotations

import asyncio
import inspect
import json
import time
import uuid
from functools import wraps
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from gateway.config import settings
from gateway.db.base import create_engine as create_db_engine, dispose_engine
from .nautilus_service import (
    NodeHandle,
    UserConflictError,
    UserNotFoundError,
    UserValidationError,
    svc,
)
from .nautilus_engine_service import EngineConfigError, EngineMode
from .logging import bind_contextvars, clear_contextvars, get_logger


logger = get_logger("gateway.api")


def _resolve_node_id(request: Request) -> str | None:
    """Attempt to extract a node identifier from the request."""

    header_value = request.headers.get("X-Node-Id")
    if header_value:
        return header_value

    path_params = request.path_params or {}
    path_node = path_params.get("node_id")
    if path_node:
        return path_node

    query_node = request.query_params.get("node_id")
    if query_node:
        return query_node

    return None


def log_websocket(func):
    """Decorator to log WebSocket lifecycle events."""

    signature = inspect.signature(func)

    @wraps(func)
    async def wrapper(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        websocket = next(
            (value for value in bound.arguments.values() if isinstance(value, WebSocket)),
            None,
        )
        if websocket is None:
            return await func(*args, **kwargs)

        node_identifier = bound.arguments.get("node_id")

        clear_contextvars()
        request_id = str(uuid.uuid4())
        bind_contextvars(request_id=request_id)
        if node_identifier:
            bind_contextvars(node_id=node_identifier)

        client_ip = websocket.client.host if websocket.client else None
        path = websocket.url.path

        logger.info(
            "websocket_connected",
            path=path,
            client_ip=client_ip,
        )

        try:
            return await func(*args, **kwargs)
        except WebSocketDisconnect:
            logger.info(
                "websocket_disconnected",
                path=path,
                client_ip=client_ip,
            )
            raise
        except Exception:
            logger.exception(
                "websocket_error",
                path=path,
                client_ip=client_ip,
            )
            raise
        finally:
            clear_contextvars()

    return wrapper


class NodeLaunchStrategyParameter(BaseModel):
    key: str
    value: str


class NodeLaunchStrategy(BaseModel):
    id: str
    name: str
    parameters: List[NodeLaunchStrategyParameter] = Field(default_factory=list)


class NodeLaunchDataSource(BaseModel):
    id: str
    label: str
    type: str
    mode: str
    enabled: bool = True


class NodeLaunchKeyReference(BaseModel):
    alias: str
    keyId: str
    required: bool = True


class NodeLaunchConstraints(BaseModel):
    maxRuntimeMinutes: int | None = None
    maxDrawdownPercent: float | None = None
    autoStopOnError: bool = True
    concurrencyLimit: int | None = None


class NodeLaunchEngineConfig(BaseModel):
    source: Optional[str] = Field(default=None, min_length=1)
    format: Optional[Literal["json", "yaml", "yml"]] = None
    content: Any


class NodeLaunchPayload(BaseModel):
    type: str
    strategy: NodeLaunchStrategy
    dataSources: List[NodeLaunchDataSource] = Field(default_factory=list)
    keyReferences: List[NodeLaunchKeyReference] = Field(default_factory=list)
    constraints: NodeLaunchConstraints = Field(default_factory=NodeLaunchConstraints)
    engineConfig: Optional[NodeLaunchEngineConfig] = None


class OrderCreatePayload(BaseModel):
    symbol: str
    venue: str
    side: str
    type: str
    quantity: float
    price: Optional[float] = None
    time_in_force: Optional[str] = None
    expire_time: Optional[str] = None
    post_only: Optional[bool] = None
    reduce_only: Optional[bool] = None
    limit_offset: Optional[float] = None
    contingency_type: Optional[str] = None
    order_list_id: Optional[str] = None
    linked_order_ids: Optional[List[str]] = None
    parent_order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    node_id: Optional[str] = None


class WatchlistUpdatePayload(BaseModel):
    favorites: List[str] = Field(default_factory=list)


class UserCreatePayload(BaseModel):
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=3)
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
    role: str = Field(default="viewer", min_length=1)
    active: bool = True


class UserUpdatePayload(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    email: Optional[str] = Field(default=None, min_length=3)
    username: Optional[str] = Field(default=None, min_length=3)
    role: Optional[str] = Field(default=None, min_length=1)
    active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8)


def build_launch_detail(payload: NodeLaunchPayload) -> str:
    parts: List[str] = []
    strategy_summary = f"Strategy {payload.strategy.name} ({payload.strategy.id})"
    if payload.strategy.parameters:
        params = ", ".join(f"{param.key}={param.value}" for param in payload.strategy.parameters)
        strategy_summary += f" [{params}]"
    parts.append(strategy_summary)

    if payload.dataSources:
        sources = ", ".join(f"{source.label or source.id}" for source in payload.dataSources)
        parts.append(f"Data: {sources}")

    if payload.keyReferences:
        keys = ", ".join(key.alias for key in payload.keyReferences)
        parts.append(f"Keys: {keys}")

    constraint_bits: List[str] = []
    constraints = payload.constraints
    if constraints.maxRuntimeMinutes is not None:
        constraint_bits.append(f"max {constraints.maxRuntimeMinutes} min")
    if constraints.maxDrawdownPercent is not None:
        constraint_bits.append(f"drawdown {constraints.maxDrawdownPercent}%")
    if constraints.concurrencyLimit is not None:
        constraint_bits.append(f"limit {constraints.concurrencyLimit}")
    if constraints.autoStopOnError:
        constraint_bits.append("auto-stop")
    if constraint_bits:
        parts.append("Constraints: " + ", ".join(constraint_bits))

    node_type = payload.type.capitalize()
    parts.insert(0, f"{node_type} node")
    return " | ".join(parts)

app = FastAPI(title="Amadeus Gateway")


@app.on_event("startup")
async def startup_event() -> None:
    """Initialise shared resources when the application starts."""

    engine = create_db_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - connectivity failures
        logger.exception("database_connectivity_failed")
        raise RuntimeError("Database connectivity check failed") from exc
    logger.info("database_ready")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Dispose of shared resources when the application stops."""

    await dispose_engine()


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every request/response pair in a structured JSON format."""

    clear_contextvars()
    request_id = str(uuid.uuid4())
    bind_contextvars(request_id=request_id)

    node_id = _resolve_node_id(request)
    if node_id:
        bind_contextvars(node_id=node_id)

    query_keys = sorted(set(request.query_params.keys()))
    client_ip = request.client.host if request.client else None

    logger.info(
        "request_received",
        method=request.method,
        path=request.url.path,
        query_keys=query_keys,
        client_ip=client_ip,
    )

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except HTTPException as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=exc.status_code,
            duration_ms=duration_ms,
            error_type="HTTPException",
        )
        clear_contextvars()
        raise
    except Exception:
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        logger.exception(
            "request_failed",
            method=request.method,
            path=request.url.path,
            duration_ms=duration_ms,
        )
        clear_contextvars()
        raise

    duration_ms = round((time.perf_counter() - started) * 1000, 3)
    logger.info(
        "request_completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    clear_contextvars()
    return response

# 👇 Разрешаем localhost и 127.0.0.1 (Angular dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok", "env": settings.env}

@app.get("/core/info")
def core_info():
    return svc.core_info()

@app.get("/nodes")
def list_nodes():
    return {"nodes": [svc.as_dict(n) for n in svc.list_nodes()]}

@app.post("/nodes/backtest/start")
def start_backtest():
    node: NodeHandle = svc.start_backtest()
    return {"node": svc.as_dict(node)}

@app.post("/nodes/live/start")
def start_live():
    node: NodeHandle = svc.start_live()
    return {"node": svc.as_dict(node)}


@app.post("/nodes/sandbox/start")
def start_sandbox():
    node: NodeHandle = svc.start_sandbox()
    return {"node": svc.as_dict(node)}


@app.post("/nodes/launch")
def launch_node(payload: NodeLaunchPayload):
    node_type = payload.type.lower()
    try:
        engine_mode = EngineMode(node_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unsupported node type '{payload.type}'")

    detail = build_launch_detail(payload)
    config_metadata: Optional[Dict[str, Any]] = None

    if payload.engineConfig is not None:
        config_input = payload.engineConfig
        config_metadata = {
            "source": config_input.source or "api",
            "format": (config_input.format or "json"),
        }
        try:
            config = svc.engine.prepare_config(
                config_input.content,
                fmt=config_input.format,
                mode=engine_mode,
            )
        except EngineConfigError as exc:
            detail_payload: Dict[str, Any] = {"message": str(exc)}
            if exc.errors:
                detail_payload["errors"] = exc.errors
            raise HTTPException(status_code=400, detail=detail_payload)
    else:
        try:
            config = svc.engine.validate_config(
                payload.dict(exclude={"engineConfig"}),
                mode=engine_mode,
            )
        except EngineConfigError as exc:
            detail_payload = {"message": str(exc)}
            if exc.errors:
                detail_payload["errors"] = exc.errors
            raise HTTPException(status_code=400, detail=detail_payload)
        config_metadata = {"source": "payload", "format": "json"}

    if node_type == "backtest":
        node = svc.start_backtest(
            detail=detail,
            config=config,
            config_metadata=config_metadata,
        )
    elif node_type == "live":
        node = svc.start_live(
            detail=detail,
            config=config,
            config_metadata=config_metadata,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported node type '{payload.type}'")
    return {"node": svc.as_dict(node)}

@app.post("/nodes/{node_id}/stop")
def stop_node(node_id: str):
    try:
        node = svc.stop_node(node_id)
        return {"node": svc.as_dict(node)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/nodes/{node_id}/restart")
def restart_node(node_id: str):
    try:
        node = svc.restart_node(node_id)
        return {"node": svc.as_dict(node)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/nodes/{node_id}")
def get_node(node_id: str):
    try:
        return svc.node_detail(node_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/nodes/{node_id}/logs")
def get_node_logs(node_id: str):
    try:
        return svc.node_logs(node_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/nodes/{node_id}/logs/export")
def export_node_logs(node_id: str):
    try:
        payload = svc.export_logs(node_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return PlainTextResponse(payload, media_type="text/plain")


@app.get("/portfolio")
def get_portfolio():
    return svc.portfolio_snapshot()


@app.get("/market/instruments")
def list_instruments(venue: Optional[str] = Query(default=None)):
    try:
        return svc.list_instruments(venue=venue)
    except ValueError as exc:  # pragma: no cover - fastapi exception adapter
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/market/watchlist")
def get_watchlist():
    return svc.get_watchlist()


@app.put("/market/watchlist")
def update_watchlist(payload: WatchlistUpdatePayload):
    return svc.update_watchlist(payload.favorites)


@app.get("/users")
def list_users():
    return svc.list_users()


@app.get("/integrations/exchanges")
def list_exchanges():
    return svc.list_available_exchanges()


@app.post("/users", status_code=201)
def create_user(payload: UserCreatePayload):
    try:
        return svc.create_user(payload.dict())
    except UserConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except UserValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/users/{user_id}")
def get_user(user_id: str):
    try:
        return svc.get_user(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.put("/users/{user_id}")
def update_user(user_id: str, payload: UserUpdatePayload):
    try:
        return svc.update_user(user_id, payload.dict(exclude_unset=True))
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except UserConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except UserValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/market/instruments/{instrument_id}/bars")
def get_historical_bars(
    instrument_id: str,
    *,
    granularity: str = Query(..., description="Bar granularity such as 1m, 1h or 1d"),
    limit: Optional[int] = Query(None, ge=1, le=5000),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
):
    try:
        return svc.get_historical_bars(
            instrument_id=instrument_id,
            granularity=granularity,
            limit=limit,
            start=start,
            end=end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/portfolio/history")
def get_portfolio_history(limit: int = 720):
    return svc.portfolio_history(limit=limit)


@app.get("/risk")
def get_risk():
    return svc.risk_snapshot()


RiskModuleStatus = Literal["up_to_date", "stale", "syncing", "error"]


class PositionLimitConfig(BaseModel):
    venue: str
    node: str
    limit: float = Field(..., gt=0)


class PositionLimitsModule(BaseModel):
    enabled: bool
    status: RiskModuleStatus
    limits: List[PositionLimitConfig] = Field(default_factory=list)


class MaxLossModule(BaseModel):
    enabled: bool
    status: RiskModuleStatus
    daily: float = Field(..., ge=0)
    weekly: float = Field(..., ge=0)


class TradeLockConfig(BaseModel):
    venue: str
    node: str
    locked: bool
    reason: Optional[str] = None


class TradeLocksModule(BaseModel):
    enabled: bool
    status: RiskModuleStatus
    locks: List[TradeLockConfig] = Field(default_factory=list)


class RiskLimitsPayload(BaseModel):
    position_limits: PositionLimitsModule
    max_loss: MaxLossModule
    trade_locks: TradeLocksModule


@app.get("/risk/limits")
def get_risk_limits():
    return svc.risk_limits_snapshot()


@app.post("/risk/limits")
def update_risk_limits(payload: RiskLimitsPayload):
    return svc.update_risk_limits(payload.dict())


@app.post("/risk/alerts/{alert_id}/ack")
def acknowledge_risk_alert(alert_id: str):
    try:
        return svc.acknowledge_risk_alert(alert_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/risk/alerts/{alert_id}/unlock")
def unlock_risk_alert(alert_id: str):
    try:
        return svc.unlock_circuit_breaker(alert_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/risk/alerts/{alert_id}/escalate")
def escalate_margin_call(alert_id: str):
    try:
        return svc.escalate_margin_call(alert_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/orders")
def get_orders():
    return svc.orders_snapshot()


@app.post("/orders")
def create_order(payload: OrderCreatePayload):
    return svc.create_order(payload.dict())


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str):
    try:
        return svc.cancel_order(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/orders/{order_id}/duplicate")
def duplicate_order(order_id: str):
    try:
        return svc.duplicate_order(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.websocket("/ws/nodes")
@log_websocket
async def ws_nodes(ws: WebSocket):
    await ws.accept()
    baseline = [svc.as_dict(n) for n in svc.list_nodes()]
    await ws.send_text(json.dumps({"event": "snapshot", "nodes": baseline}))
    try:
        async for payload in svc.node_stream():
            await ws.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        return


@app.websocket("/ws/nodes/{node_id}/logs")
@log_websocket
async def ws_node_logs(node_id: str, ws: WebSocket):
    await ws.accept()
    try:
        await ws.send_text(json.dumps(svc.stream_snapshot(node_id)))
    except ValueError:
        await ws.send_text(json.dumps({"logs": [], "lifecycle": []}))
        await ws.close(code=1008)
        return

    try:
        async for payload in svc.node_log_stream(node_id):
            await ws.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        return


@app.websocket("/ws/nodes/{node_id}/metrics")
@log_websocket
async def ws_node_metrics(node_id: str, ws: WebSocket):
    await ws.accept()
    try:
        await ws.send_text(json.dumps(svc.metrics_series(node_id)))
    except ValueError:
        await ws.send_text(json.dumps({"series": {}, "latest": None}))
        await ws.close(code=1008)
        return

    try:
        async for payload in svc.node_metrics_stream(node_id):
            await ws.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        return


@app.websocket("/ws/risk/limit-breaches")
@log_websocket
async def ws_risk_limit_breaches(ws: WebSocket):
    await ws.accept()
    await ws.send_text(json.dumps(svc.risk_limit_breaches_stream_payload()))
    try:
        async for payload in svc.risk_alert_stream():
            if payload.get("alert", {}).get("category") == "limit_breach":
                await ws.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        return


@app.websocket("/ws/risk/circuit-breakers")
@log_websocket
async def ws_risk_circuit_breakers(ws: WebSocket):
    await ws.accept()
    await ws.send_text(json.dumps(svc.risk_circuit_breakers_stream_payload()))
    try:
        async for payload in svc.risk_alert_stream():
            if payload.get("alert", {}).get("category") == "circuit_breaker":
                await ws.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        return


@app.websocket("/ws/risk/margin-calls")
@log_websocket
async def ws_risk_margin_calls(ws: WebSocket):
    await ws.accept()
    await ws.send_text(json.dumps(svc.risk_margin_calls_stream_payload()))
    try:
        async for payload in svc.risk_alert_stream():
            if payload.get("alert", {}).get("category") == "margin_call":
                await ws.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        return


@app.websocket("/ws/portfolio/balances")
@log_websocket
async def ws_portfolio_balances(ws: WebSocket):
    await ws.accept()
    await ws.send_text(json.dumps(svc.portfolio_balances_stream_payload()))
    try:
        async for payload in svc.portfolio_stream():
            await ws.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        return


@app.websocket("/ws/portfolio/positions")
@log_websocket
async def ws_portfolio_positions(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            payload = svc.portfolio_positions_stream_payload()
            await ws.send_text(json.dumps(payload))
            await asyncio.sleep(1.1)
    except WebSocketDisconnect:
        return


@app.websocket("/ws/portfolio/movements")
@log_websocket
async def ws_portfolio_movements(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            payload = svc.portfolio_movements_stream_payload()
            await ws.send_text(json.dumps(payload))
            await asyncio.sleep(1.6)
    except WebSocketDisconnect:
        return


@app.websocket("/ws/orders")
@log_websocket
async def ws_orders(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            payload = svc.orders_stream_payload()
            await ws.send_text(json.dumps(payload))
            await asyncio.sleep(1.2)
    except WebSocketDisconnect:
        return
