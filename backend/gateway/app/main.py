from __future__ import annotations

import asyncio
import inspect
import json
import time
import uuid
from copy import deepcopy
from datetime import timezone
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.datastructures import UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.config import settings
from gateway.db.models import (
    ApiKey,
    Config as DbConfig,
    ConfigFormat,
    ConfigSource,
    Node as DbNode,
    NodeMode as DbNodeMode,
    NodeStatus as DbNodeStatus,
    User as DbUser,
)
from .db import engine, get_session
from .nautilus_service import (
    EngineUnavailableError,
    NodeHandle,
    UserConflictError,
    UserNotFoundError,
    UserValidationError,
    svc,
)
from .nautilus_engine_service import EngineConfigError, EngineMode, EngineNodeHandle
from .logging import bind_contextvars, clear_contextvars, get_logger
from .routes.data import router as data_router
from .routes.keys import router as keys_router
from .routes.orders import router as orders_router
from .routes.strategies import router as strategies_router
from .routes.users import router as users_router
from .routes.risk import router as risk_router


logger = get_logger("gateway.api")


async def _resolve_primary_user(session: AsyncSession) -> DbUser:
    result = await session.execute(select(DbUser).order_by(DbUser.id.asc()).limit(1))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="No user accounts available for launch"
        )
    return user


def _normalise_config_source(value: Optional[str]) -> ConfigSource:
    if value is None:
        return ConfigSource.UI

    candidate = value.strip().lower()
    try:
        return ConfigSource(candidate)
    except ValueError:
        if candidate in {"api", "payload", "json", "form"}:
            return ConfigSource.UI
        if candidate in {"upload", "file"}:
            return ConfigSource.UPLOAD
        return ConfigSource.UI


def _normalise_config_format(value: Optional[str]) -> ConfigFormat:
    if value is None:
        return ConfigFormat.JSON

    candidate = value.strip().lower()
    if candidate == "yml":
        candidate = "yaml"
    try:
        return ConfigFormat(candidate)
    except ValueError:
        return ConfigFormat.JSON


def _persist_node_record(
    session: AsyncSession,
    *,
    user_id: int,
    mode: EngineMode,
    config: Dict[str, Any],
    config_meta: Dict[str, Any],
    detail: Optional[str],
    status: DbNodeStatus,
    handle: Optional[EngineNodeHandle] = None,
    error: Optional[str] = None,
) -> Tuple[DbNode, DbConfig]:
    strategy = config.get("strategy") or {}
    strategy_id = strategy.get("id")
    summary: Dict[str, Any] = {
        "external_id": handle.id if handle else None,
        "mode": mode.value,
        "detail": detail,
        "status": status.value,
        "config_version": handle.config_version if handle else 0,
        "config_source": config_meta.get("source"),
        "config_format": config_meta.get("format"),
    }
    if strategy:
        strategy_summary: Dict[str, Any] = {}
        if strategy.get("id") is not None:
            strategy_summary["id"] = strategy.get("id")
        if strategy.get("name") is not None:
            strategy_summary["name"] = strategy.get("name")
        parameters = strategy.get("parameters")
        if isinstance(parameters, list) and parameters:
            strategy_summary["parameters"] = [deepcopy(param) for param in parameters]
        summary["strategy"] = strategy_summary
    if handle is not None:
        summary["adapters"] = deepcopy(handle.adapters)
        summary["started_at"] = handle.started_at.isoformat()
        if handle.metrics:
            summary["metrics"] = deepcopy(handle.metrics)
            for metric_key in ("pnl", "equity", "latency_ms", "cpu_percent", "memory_mb"):
                metric_value = handle.metrics.get(metric_key)
                if metric_value is not None:
                    summary[metric_key] = metric_value
    if error:
        summary["error"] = error

    node_record = DbNode(
        user_id=user_id,
        mode=DbNodeMode(mode.value),
        strategy_id=strategy_id,
        status=status,
        started_at=(handle.started_at if handle else None),
        summary=summary,
    )
    session.add(node_record)

    config_record = DbConfig(
        node=node_record,
        version=(handle.config_version if handle else 1),
        source=_normalise_config_source(config_meta.get("source")),
        format=_normalise_config_format(config_meta.get("format")),
        content=deepcopy(config),
    )
    session.add(config_record)
    return node_record, config_record


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


def _ensure_engine_available() -> None:
    """Raise an HTTP error when Nautilus is unavailable and mocks are disabled."""

    try:
        svc.require_engine()
    except EngineUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "message": str(exc),
                "hint": "Install nautilus-trader or set AMAD_USE_MOCK=true.",
            },
        ) from exc


def log_websocket(func):
    """Decorator to log WebSocket lifecycle events."""

    signature = inspect.signature(func)

    @wraps(func)
    async def wrapper(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        websocket = next(
            (
                value
                for value in bound.arguments.values()
                if isinstance(value, WebSocket)
            ),
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


class NodeLaunchAdapterSelection(BaseModel):
    venue: str
    alias: Optional[str] = None
    key_id: Optional[str] = Field(default=None, alias="keyId")
    enable_data: bool = Field(default=True, alias="enableData")
    enable_trading: bool = Field(default=True, alias="enableTrading")
    sandbox: bool = False
    options: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("venue")
    @classmethod
    def _normalise_venue(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Venue is required")
        return value.strip().upper()

    @field_validator("alias")
    @classmethod
    def _normalise_alias(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip().lower()
        return cleaned or None

    @field_validator("key_id")
    @classmethod
    def _normalise_key_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("options", mode="before")
    @classmethod
    def _ensure_options(cls, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        raise ValueError("Options must be an object")

    model_config = ConfigDict(populate_by_name=True)


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
    adapters: List[NodeLaunchAdapterSelection] = Field(default_factory=list)
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
        params = ", ".join(
            f"{param.key}={param.value}" for param in payload.strategy.parameters
        )
        strategy_summary += f" [{params}]"
    parts.append(strategy_summary)

    if payload.dataSources:
        sources = ", ".join(
            f"{source.label or source.id}" for source in payload.dataSources
        )
        parts.append(f"Data: {sources}")

    if payload.keyReferences:
        keys = ", ".join(key.alias for key in payload.keyReferences)
        parts.append(f"Keys: {keys}")

    if payload.adapters:
        adapter_bits: List[str] = []
        for adapter in payload.adapters:
            roles: List[str] = []
            if adapter.enable_data:
                roles.append("data")
            if adapter.enable_trading:
                roles.append("trading")
            role_text = "/".join(roles) if roles else "disabled"
            key_text = adapter.key_id or "no-key"
            adapter_bits.append(f"{adapter.venue} [{role_text}] ({key_text})")
        parts.append(f"Adapters: {', '.join(adapter_bits)}")

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


async def _fetch_user_api_key(
    session: AsyncSession,
    *,
    user_id: int,
    key_id: str,
    expected_venue: str,
) -> ApiKey:
    stmt = (
        select(ApiKey)
        .where(ApiKey.user_id == user_id)
        .where(ApiKey.key_id == key_id)
    )
    result = await session.execute(stmt)
    record = result.scalars().first()
    if record is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"API key '{key_id}' is not registered for the current user.",
        )

    expected = expected_venue.upper()
    actual = (record.venue or "").upper()
    if actual != expected:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                f"API key '{key_id}' is registered for venue '{record.venue}', "
                f"expected '{expected_venue}'."
            ),
        )
    return record


async def _apply_launch_adapters(
    session: AsyncSession,
    *,
    user: DbUser,
    mode: EngineMode,
    config: Dict[str, Any],
    selections: Sequence[NodeLaunchAdapterSelection],
) -> None:
    if mode not in {EngineMode.LIVE, EngineMode.SANDBOX}:
        return

    if not selections:
        if mode == EngineMode.LIVE:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Live nodes require at least one configured exchange adapter.",
            )
        return

    alias_set: set[str] = set()
    data_sources: List[Dict[str, Any]] = []
    key_reference_map: Dict[str, Dict[str, Any]] = {}

    for selection in selections:
        alias = (selection.alias or selection.venue.lower()).strip().lower()
        if not alias:
            alias = selection.venue.lower()
        alias_set.add(alias)

        if not selection.enable_data and not selection.enable_trading:
            continue

        key_id = selection.key_id
        if mode == EngineMode.LIVE and not key_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Exchange {selection.venue} requires an API key for live mode.",
            )

        if selection.enable_trading and not key_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Trading access for {selection.venue} requires an API key.",
            )

        if key_id:
            record = await _fetch_user_api_key(
                session,
                user_id=user.id,
                key_id=key_id,
                expected_venue=selection.venue,
            )
            key_reference_map[alias] = {
                "alias": alias,
                "keyId": record.key_id,
                "required": selection.enable_trading or mode == EngineMode.LIVE,
            }

        base_options = dict(selection.options or {})
        base_options.setdefault("venue", selection.venue)
        if selection.sandbox or mode == EngineMode.SANDBOX:
            base_options.setdefault("testnet", True)
        base_options.setdefault("keyAlias", alias)

        if selection.enable_data:
            data_sources.append(
                {
                    "id": f"{alias}-data",
                    "label": f"{selection.venue} market data",
                    "type": "live",
                    "mode": "read",
                    "enabled": True,
                    "options": base_options,
                }
            )

        if selection.enable_trading:
            data_sources.append(
                {
                    "id": f"{alias}-trading",
                    "label": f"{selection.venue} trading",
                    "type": "live",
                    "mode": "write",
                    "enabled": True,
                    "options": base_options,
                }
            )

    if mode == EngineMode.LIVE and not data_sources:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Live nodes require at least one enabled exchange adapter.",
        )

    existing_sources = []
    raw_sources = config.get("dataSources")
    if isinstance(raw_sources, list):
        for source in raw_sources:
            if isinstance(source, dict):
                existing_sources.append(source)

    filtered_sources = [
        source
        for source in existing_sources
        if not any(
            str(source.get("id") or "").lower().startswith(alias)
            for alias in alias_set
        )
    ]
    filtered_sources.extend(data_sources)
    config["dataSources"] = filtered_sources

    existing_refs = []
    raw_refs = config.get("keyReferences")
    if isinstance(raw_refs, list):
        for ref in raw_refs:
            if isinstance(ref, dict):
                existing_refs.append(ref)

    filtered_refs = [
        ref
        for ref in existing_refs
        if str(ref.get("alias") or "").lower() not in alias_set
    ]
    filtered_refs.extend(key_reference_map.values())
    config["keyReferences"] = filtered_refs

    if selections:
        config["adapters"] = [
            selection.model_dump(by_alias=True) for selection in selections
        ]
app = FastAPI(title="Amadeus Gateway")
app.include_router(risk_router)
app.include_router(data_router, prefix="/api")
app.include_router(keys_router, prefix="/api")
app.include_router(orders_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(strategies_router, prefix="/api")


@app.on_event("startup")
async def startup_event() -> None:
    """Initialise shared resources when the application starts."""

    database_url = settings.database_url
    if not database_url or not database_url.strip():
        logger.error("database_url_missing")
        raise RuntimeError("Database URL is not configured")

    logger.info("database_configuration_loaded", database_url=database_url)

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

    await engine.dispose()


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
    return svc.health_status()


@app.get("/core/info")
def core_info():
    return svc.core_info()


@app.get("/nodes")
def list_nodes():
    return {"nodes": [svc.as_dict(n) for n in svc.list_nodes()]}


@app.post("/nodes/backtest/start")
def start_backtest():
    _ensure_engine_available()
    node: NodeHandle = svc.start_backtest()
    return {"node": svc.as_dict(node)}


@app.post("/nodes/live/start")
def start_live():
    _ensure_engine_available()
    node: NodeHandle = svc.start_live()
    return {"node": svc.as_dict(node)}


@app.post("/nodes/sandbox/start")
def start_sandbox():
    _ensure_engine_available()
    node: NodeHandle = svc.start_sandbox()
    return {"node": svc.as_dict(node)}


@app.post("/nodes/launch")
async def launch_node(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    _ensure_engine_available()

    content_type = request.headers.get("content-type", "")
    config_metadata: Dict[str, Any] = {}
    detail: Optional[str] = None

    user: Optional[DbUser] = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        raw_mode = str(form.get("mode") or form.get("type") or "").strip().lower()
        if not raw_mode:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="Field 'mode' is required"
            )
        try:
            engine_mode = EngineMode(raw_mode)
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported node mode '{raw_mode}'",
            )

        upload = form.get("config_file") or form.get("config") or form.get("file")
        fmt_hint = str(form.get("format") or "").strip() or None
        if fmt_hint:
            config_metadata["format"] = fmt_hint

        if isinstance(upload, UploadFile):
            filename = upload.filename or "upload"
            config_metadata.setdefault("source", "upload")
            suffix = Path(filename).suffix.lstrip(".")
            if suffix and "format" not in config_metadata:
                config_metadata["format"] = suffix
            try:
                upload.file.seek(0)
                config = svc.engine.load_config(upload.file, mode=engine_mode)
            except EngineConfigError as exc:
                detail_payload: Dict[str, Any] = {"message": str(exc)}
                if exc.errors:
                    detail_payload["errors"] = exc.errors
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=detail_payload)
            finally:
                await upload.close()
        else:
            raw_payload = form.get("config_json") or form.get("config")
            if raw_payload is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail="Configuration payload is required",
                )
            config_metadata.setdefault("source", "form")
            try:
                config = svc.engine.prepare_config(
                    raw_payload, fmt=config_metadata.get("format"), mode=engine_mode
                )
            except EngineConfigError as exc:
                detail_payload = {"message": str(exc)}
                if exc.errors:
                    detail_payload["errors"] = exc.errors
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=detail_payload)

        strategy = config.get("strategy") or {}
        strategy_name = strategy.get("name") or strategy.get("id") or "strategy"
        detail = (
            str(form.get("detail") or "").strip()
            or f"{engine_mode.value.title()} node for {strategy_name}"
        )
    else:
        try:
            payload_dict = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON payload: {exc.msg}",
            ) from exc

        try:
            payload = NodeLaunchPayload.model_validate(payload_dict)
        except ValidationError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=json.loads(exc.json()),
            ) from exc

        node_type = payload.type.lower()
        try:
            engine_mode = EngineMode(node_type)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported node type '{payload.type}'",
            ) from exc

        detail = build_launch_detail(payload)

        user = await _resolve_primary_user(session)

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
                detail_payload = {"message": str(exc)}
                if exc.errors:
                    detail_payload["errors"] = exc.errors
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=detail_payload)
        else:
            config_payload = payload.model_dump(exclude={"engineConfig"})
            await _apply_launch_adapters(
                session,
                user=user,
                mode=engine_mode,
                config=config_payload,
                selections=payload.adapters,
            )
            try:
                config = svc.engine.validate_config(config_payload, mode=engine_mode)
            except EngineConfigError as exc:
                detail_payload = {"message": str(exc)}
                if exc.errors:
                    detail_payload["errors"] = exc.errors
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=detail_payload)
            config_metadata = {"source": "payload", "format": "json"}

    if user is None:
        user = await _resolve_primary_user(session)

    try:
        engine_handle = svc.engine.launch_node(
            config, engine_mode, user_id=str(user.id)
        )
    except EngineConfigError as exc:
        detail_payload = {"message": str(exc)}
        if exc.errors:
            detail_payload["errors"] = exc.errors
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=detail_payload)
    except Exception as exc:
        logger.exception("node_launch_failed", mode=engine_mode.value)
        try:
            await _record_launch(
                session,
                user_id=user.id,
                mode=engine_mode,
                config=config,
                config_metadata=config_metadata,
                detail=detail,
                status=DbNodeStatus.ERROR,
                handle=None,
                error=str(exc),
            )
        except Exception:
            await session.rollback()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": f"Failed to start node: {exc}"},
        ) from exc

    try:
        node_record = await _record_launch(
            session,
            user_id=user.id,
            mode=engine_mode,
            config=config,
            config_metadata=config_metadata,
            detail=detail,
            status=DbNodeStatus.RUNNING,
            handle=engine_handle,
        )
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": f"Failed to persist node launch: {exc}"},
        ) from exc

    started_at = engine_handle.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    node_snapshot: Optional[Dict[str, Any]] = None
    try:
        node_snapshot = next(
            (
                svc.as_dict(node)
                for node in svc.list_nodes()
                if node.id == engine_handle.id
            ),
            None,
        )
    except Exception:
        node_snapshot = None

    response_node: Dict[str, Any]
    if node_snapshot is not None:
        response_node = node_snapshot
    else:
        response_node = {
            "id": engine_handle.id,
            "mode": engine_mode.value,
            "status": DbNodeStatus.RUNNING.value,
            "detail": detail,
            "created_at": started_at.isoformat().replace("+00:00", "Z"),
            "updated_at": started_at.isoformat().replace("+00:00", "Z"),
            "metrics": {},
            "adapters": deepcopy(engine_handle.adapters),
        }

    response_node.setdefault("mode", engine_mode.value)
    response_node.setdefault("status", DbNodeStatus.RUNNING.value)
    response_node.setdefault("detail", detail)
    response_node.setdefault(
        "started_at", started_at.isoformat().replace("+00:00", "Z")
    )
    response_node.setdefault("adapters", deepcopy(engine_handle.adapters))
    response_node["config_version"] = engine_handle.config_version
    response_node["db_id"] = node_record.id

    summary_from_db = deepcopy(node_record.summary)
    summary_from_runtime = deepcopy(response_node.get("summary") or {})
    merged_summary = summary_from_db
    merged_summary.update(summary_from_runtime)
    merged_summary.setdefault("external_id", engine_handle.id)
    merged_summary.setdefault("mode", engine_mode.value)
    merged_summary.setdefault("status", DbNodeStatus.RUNNING.value)
    if detail and "detail" not in merged_summary:
        merged_summary["detail"] = detail
    response_node["summary"] = merged_summary

    return {"node": response_node}


async def _record_launch(
    session: AsyncSession,
    *,
    user_id: int,
    mode: EngineMode,
    config: Dict[str, Any],
    config_metadata: Dict[str, Any],
    detail: Optional[str],
    status: DbNodeStatus,
    handle: Optional[EngineNodeHandle],
    error: Optional[str] = None,
) -> DbNode:
    node_record, _ = _persist_node_record(
        session,
        user_id=user_id,
        mode=mode,
        config=config,
        config_meta=config_metadata,
        detail=detail,
        status=status,
        handle=handle,
        error=error,
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return node_record


@app.post("/nodes/{node_id}/stop")
def stop_node(node_id: str):
    _ensure_engine_available()
    try:
        node = svc.stop_node(node_id)
        return {"node": svc.as_dict(node)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/nodes/{node_id}/restart")
def restart_node(node_id: str):
    _ensure_engine_available()
    try:
        node = svc.restart_node(node_id)
        return {"node": svc.as_dict(node)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/nodes/{node_id}")
def get_node(node_id: str):
    _ensure_engine_available()
    try:
        return svc.node_detail(node_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/nodes/{node_id}/logs")
def download_node_logs(node_id: str):
    _ensure_engine_available()
    try:
        path = svc.node_log_file(node_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if not path.exists():
        try:
            payload = svc.export_logs(node_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return PlainTextResponse(payload, media_type="text/plain")

    filename = f"{node_id}.log" if not str(node_id).endswith(".log") else str(node_id)
    return FileResponse(
        path,
        media_type="text/plain",
        filename=filename,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/nodes/{node_id}/logs/entries")
def get_node_logs(node_id: str):
    _ensure_engine_available()
    try:
        return svc.node_logs(node_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/nodes/{node_id}/logs/export")
def export_node_logs(node_id: str):
    _ensure_engine_available()
    try:
        payload = svc.export_logs(node_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return PlainTextResponse(payload, media_type="text/plain")


@app.get("/portfolio")
def get_portfolio():
    _ensure_engine_available()
    return svc.portfolio_snapshot()


@app.get("/market/instruments")
def list_instruments(venue: Optional[str] = Query(default=None)):
    _ensure_engine_available()
    try:
        return svc.list_instruments(venue=venue)
    except ValueError as exc:  # pragma: no cover - fastapi exception adapter
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/market/watchlist")
def get_watchlist():
    _ensure_engine_available()
    return svc.get_watchlist()


@app.put("/market/watchlist")
def update_watchlist(payload: WatchlistUpdatePayload):
    _ensure_engine_available()
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
    _ensure_engine_available()
    return svc.orders_snapshot()


@app.post("/orders")
def create_order(payload: OrderCreatePayload):
    _ensure_engine_available()
    return svc.create_order(payload.dict())


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str):
    _ensure_engine_available()
    try:
        return svc.cancel_order(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/orders/{order_id}/duplicate")
def duplicate_order(order_id: str):
    _ensure_engine_available()
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
        snapshot = svc.orders_snapshot()
    except Exception:  # pragma: no cover - defensive guard
        snapshot = {"orders": [], "executions": []}
    if snapshot:
        baseline = {"event": "snapshot", **snapshot}
        await ws.send_text(json.dumps(baseline))
    try:
        async for payload in svc.orders_stream():
            await ws.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        return
