"""Order management API endpoints."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.base import create_session

from ..nautilus_service import EngineUnavailableError, svc
from ..state_sync import EngineExecution, EngineOrder

LOGGER = logging.getLogger("gateway.api.orders")
router = APIRouter(prefix="/orders", tags=["orders"])


async def get_session() -> AsyncIterator[AsyncSession]:
    session = create_session()
    try:
        yield session
    finally:  # pragma: no cover - cleanup
        await session.close()


_SUPPORTED_TYPES = {
    "market",
    "limit",
    "stop",
    "stop_limit",
}
_SUPPORTED_TIFS = {"GTC", "IOC", "FOK", "GTD", "DAY"}
_SUPPORTED_CONTINGENCIES = {"OCO", "OTO"}


def _parse_timestamp(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    candidate = value.strip()
    if not candidate:
        return datetime.now(tz=timezone.utc)
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return datetime.now(tz=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive guard
        return None


def _normalise_order_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(payload)
    summary.setdefault("instructions", payload.get("instructions") or {})
    summary.setdefault("raw", payload)
    return summary


class ExecutionReportResource(BaseModel):
    order_id: str
    execution_id: str
    symbol: Optional[str] = None
    venue: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[float] = None
    side: Optional[str] = None
    liquidity: Optional[str] = None
    fees: Optional[float] = None
    timestamp: datetime
    node_id: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class OrderResource(BaseModel):
    order_id: str
    client_order_id: Optional[str] = None
    venue_order_id: Optional[str] = None
    symbol: Optional[str] = None
    venue: Optional[str] = None
    side: Optional[str] = None
    type: Optional[str] = None
    quantity: Optional[float] = None
    filled_quantity: Optional[float] = None
    price: Optional[float] = None
    average_price: Optional[float] = None
    status: Optional[str] = None
    time_in_force: Optional[str] = None
    expire_time: Optional[str] = None
    post_only: Optional[bool] = None
    reduce_only: Optional[bool] = None
    limit_offset: Optional[float] = None
    contingency_type: Optional[str] = None
    order_list_id: Optional[str] = None
    linked_order_ids: Optional[List[str]] = None
    parent_order_id: Optional[str] = None
    node_id: Optional[str] = None
    instructions: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(populate_by_name=True)


class OrdersResponse(BaseModel):
    orders: List[OrderResource]
    executions: List[ExecutionReportResource] = Field(default_factory=list)


class OrderResponse(BaseModel):
    order: OrderResource


class OrderCreateRequest(BaseModel):
    instrument: Optional[str] = Field(default=None, description="Instrument identifier")
    symbol: Optional[str] = Field(default=None, description="Instrument symbol")
    venue: Optional[str] = Field(default=None, description="Trading venue code")
    side: str
    type: str
    quantity: float
    price: Optional[float] = None
    time_in_force: Optional[str] = Field(default="GTC")
    expire_time: Optional[str] = None
    post_only: Optional[bool] = None
    reduce_only: Optional[bool] = None
    limit_offset: Optional[float] = None
    contingency_type: Optional[str] = None
    order_list_id: Optional[str] = None
    linked_order_ids: Optional[Iterable[str]] = None
    parent_order_id: Optional[str] = None
    node_id: Optional[str] = None
    client_order_id: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator("instrument", "symbol", "venue", "parent_order_id", "order_list_id", "client_order_id", mode="before")
    @classmethod
    def _normalise_str(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @field_validator("side")
    @classmethod
    def _validate_side(cls, value: str) -> str:
        side = str(value or "").strip().lower()
        if side not in {"buy", "sell"}:
            raise ValueError("Side must be either 'buy' or 'sell'")
        return side

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        order_type = str(value or "").strip().lower()
        if order_type not in _SUPPORTED_TYPES:
            raise ValueError(
                f"Unsupported order type '{value}'. Supported values: {', '.join(sorted(_SUPPORTED_TYPES))}."
            )
        return order_type

    @field_validator("time_in_force")
    @classmethod
    def _validate_tif(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        tif = str(value).strip().upper()
        if tif not in _SUPPORTED_TIFS:
            raise ValueError(
                f"Unsupported time in force '{value}'. Supported values: {', '.join(sorted(_SUPPORTED_TIFS))}."
            )
        return tif

    @field_validator("linked_order_ids", mode="before")
    @classmethod
    def _normalise_links(cls, value: Optional[Iterable[str]]) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            tokens = value.replace(",", " ").split()
        else:
            tokens = list(value)
        result: List[str] = []
        for token in tokens:
            cleaned = str(token).strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
        return result

    @field_validator("quantity")
    @classmethod
    def _validate_quantity(cls, value: float) -> float:
        try:
            quantity = float(value)
        except (TypeError, ValueError):  # pragma: no cover - defensive guard
            raise ValueError("Quantity must be a number") from None
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero")
        return quantity

    @field_validator("price")
    @classmethod
    def _validate_price(cls, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):  # pragma: no cover - defensive guard
            raise ValueError("Numeric fields must be valid numbers") from None
        if not numeric > 0:
            raise ValueError("Numeric fields must be greater than zero")
        return numeric

    @field_validator("limit_offset")
    @classmethod
    def _validate_limit_offset(cls, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):  # pragma: no cover - defensive guard
            raise ValueError("Limit offset must be a number") from None

    @model_validator(mode="after")
    def _validate_combinations(self) -> "OrderCreateRequest":
        symbol = self.symbol
        venue = self.venue
        if self.instrument and (not symbol or not venue):
            parts = self.instrument.split(":")
            if len(parts) >= 2:
                venue = venue or parts[0]
                symbol = symbol or parts[-1]
        if not symbol or not venue:
            raise ValueError("Instrument symbol and venue must be provided")
        self.symbol = symbol.upper()
        self.venue = venue.upper()

        if self.contingency_type:
            contingency = self.contingency_type.strip().upper()
            if contingency not in _SUPPORTED_CONTINGENCIES:
                raise ValueError(
                    "Contingency type must be one of: " + ", ".join(sorted(_SUPPORTED_CONTINGENCIES))
                )
            self.contingency_type = contingency
            if contingency == "OCO" and not self.order_list_id:
                raise ValueError("Order list ID is required for OCO contingency")
            if contingency == "OTO" and not self.parent_order_id:
                raise ValueError("Parent order ID is required for OTO contingency")
            if not self.linked_order_ids:
                raise ValueError("Linked order IDs must be provided when using a contingency")
        else:
            self.contingency_type = None

        if self.time_in_force == "GTD" and not self.expire_time:
            raise ValueError("Expire time is required for GTD orders")

        if self.type in {"limit", "stop", "stop_limit"} and not self.price:
            field = "Price" if self.type == "limit" else "Trigger price"
            raise ValueError(f"{field} is required for {self.type.replace('_', ' ')} orders")

        if self.type == "stop_limit" and self.limit_offset is None:
            raise ValueError("Limit offset is required for stop-limit orders")

        return self

    def to_engine_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "symbol": self.symbol,
            "venue": self.venue,
            "side": self.side,
            "type": self.type,
            "quantity": float(self.quantity),
        }
        if self.price is not None:
            payload["price"] = float(self.price)
        if self.time_in_force:
            payload["time_in_force"] = self.time_in_force
        if self.expire_time:
            payload["expire_time"] = self.expire_time
        if self.post_only is not None:
            payload["post_only"] = bool(self.post_only)
        if self.reduce_only is not None:
            payload["reduce_only"] = bool(self.reduce_only)
        if self.limit_offset is not None:
            payload["limit_offset"] = float(self.limit_offset)
        if self.contingency_type:
            payload["contingency_type"] = self.contingency_type
        if self.order_list_id:
            payload["order_list_id"] = self.order_list_id
        if self.linked_order_ids:
            payload["linked_order_ids"] = list(self.linked_order_ids)
        if self.parent_order_id:
            payload["parent_order_id"] = self.parent_order_id
        if self.node_id:
            payload["node_id"] = self.node_id
        if self.client_order_id:
            payload["client_order_id"] = self.client_order_id
        if self.instrument:
            payload["instrument"] = self.instrument
        return payload


async def _load_orders(
    session: AsyncSession,
    statement: Optional[Select[tuple[EngineOrder]]] = None,
) -> List[OrderResource]:
    if statement is None:
        statement = select(EngineOrder).order_by(EngineOrder.created_at.desc())
    result = await session.execute(statement)
    orders: List[OrderResource] = []
    for record in result.scalars():
        raw = record.raw or {}
        instructions = record.instructions or raw.get("instructions") or {}
        orders.append(
            OrderResource(
                order_id=record.order_id,
                client_order_id=record.client_order_id,
                venue_order_id=record.venue_order_id,
                symbol=record.symbol,
                venue=record.venue,
                side=(record.side or raw.get("side")),
                type=(record.type or raw.get("type")),
                quantity=_coerce_float(record.quantity),
                filled_quantity=_coerce_float(record.filled_quantity),
                price=_coerce_float(record.price),
                average_price=_coerce_float(record.average_price),
                status=record.status,
                time_in_force=record.time_in_force or raw.get("time_in_force"),
                expire_time=record.expire_time or raw.get("expire_time"),
                post_only=raw.get("post_only"),
                reduce_only=raw.get("reduce_only"),
                limit_offset=_coerce_float(raw.get("limit_offset")),
                contingency_type=raw.get("contingency_type"),
                order_list_id=raw.get("order_list_id"),
                linked_order_ids=list(raw.get("linked_order_ids") or []),
                parent_order_id=raw.get("parent_order_id"),
                node_id=record.node_id or raw.get("node_id"),
                instructions=instructions,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )
    return orders


async def _load_executions(session: AsyncSession) -> List[ExecutionReportResource]:
    statement: Select[tuple[EngineExecution]] = select(EngineExecution).order_by(EngineExecution.timestamp.desc())
    result = await session.execute(statement)
    executions: List[ExecutionReportResource] = []
    for record in result.scalars():
        executions.append(
            ExecutionReportResource(
                order_id=record.order_id,
                execution_id=record.execution_id,
                symbol=record.symbol,
                venue=record.venue,
                price=_coerce_float(record.price),
                quantity=_coerce_float(record.quantity),
                side=record.side,
                liquidity=record.liquidity,
                fees=_coerce_float(record.fees),
                timestamp=record.timestamp,
                node_id=record.node_id,
            )
        )
    return executions


async def _upsert_engine_order(session: AsyncSession, payload: Dict[str, Any]) -> None:
    order_id = str(payload.get("order_id") or "").strip()
    if not order_id:
        LOGGER.debug("order_persistence_skipped", reason="missing_id", payload=payload)
        return
    record = await session.get(EngineOrder, order_id)
    created_at = _parse_timestamp(payload.get("created_at"))
    updated_at = _parse_timestamp(payload.get("updated_at"))
    if record is None:
        record = EngineOrder(order_id=order_id)
        session.add(record)
    record.client_order_id = payload.get("client_order_id")
    record.venue_order_id = payload.get("venue_order_id")
    record.node_id = payload.get("node_id")
    record.symbol = payload.get("symbol")
    record.venue = payload.get("venue")
    record.side = payload.get("side")
    record.type = payload.get("type")
    record.status = payload.get("status") or record.status
    record.quantity = _coerce_float(payload.get("quantity"))
    record.filled_quantity = _coerce_float(payload.get("filled_quantity"))
    record.price = _coerce_float(payload.get("price"))
    record.average_price = _coerce_float(payload.get("average_price"))
    record.time_in_force = payload.get("time_in_force")
    record.expire_time = payload.get("expire_time")
    record.instructions = payload.get("instructions")
    record.raw = payload
    record.created_at = created_at
    record.updated_at = updated_at


@router.get("/", response_model=OrdersResponse)
async def list_orders(session: AsyncSession = Depends(get_session)) -> OrdersResponse:
    try:
        svc.require_engine()
    except EngineUnavailableError as exc:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "message": str(exc),
                "hint": "Install nautilus-trader or enable AMAD_USE_MOCK.",
            },
        ) from exc
    try:
        orders = await _load_orders(session)
        executions = await _load_executions(session)
        return OrdersResponse(orders=orders, executions=executions)
    except Exception:  # pragma: no cover - defensive guard
        LOGGER.exception("orders_query_failed")
        snapshot = svc.orders_snapshot()
        orders_payload = snapshot.get("orders") or []
        executions_payload = snapshot.get("executions") or []
        orders: List[OrderResource] = []
        for entry in orders_payload:
            if not isinstance(entry, dict):
                continue
            try:
                orders.append(OrderResource(**entry))
            except Exception:  # pragma: no cover - defensive guard
                continue
        executions: List[ExecutionReportResource] = []
        for execution in executions_payload:
            if not isinstance(execution, dict):
                continue
            order_id = execution.get("order_id")
            execution_id = execution.get("execution_id") or execution.get("trade_id")
            if not order_id or not execution_id:
                continue
            executions.append(
                ExecutionReportResource(
                    order_id=order_id,
                    execution_id=execution_id,
                    symbol=execution.get("symbol"),
                    venue=execution.get("venue"),
                    price=_coerce_float(execution.get("price")),
                    quantity=_coerce_float(execution.get("quantity")),
                    side=execution.get("side"),
                    liquidity=execution.get("liquidity"),
                    fees=_coerce_float(execution.get("fees")),
                    timestamp=_parse_timestamp(execution.get("timestamp")),
                    node_id=execution.get("node_id"),
                )
            )
        return OrdersResponse(orders=orders, executions=executions)


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str, session: AsyncSession = Depends(get_session)) -> OrderResponse:
    orders = await _load_orders(
        session,
        select(EngineOrder).where(EngineOrder.order_id == order_id).limit(1),
    )
    if not orders:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return OrderResponse(order=orders[0])


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(payload: OrderCreateRequest, session: AsyncSession = Depends(get_session)) -> OrderResponse:
    engine_payload = payload.to_engine_payload()
    try:
        ensure_engine = getattr(svc, "require_engine", None)
        if callable(ensure_engine):
            ensure_engine()
        response = svc.create_order(engine_payload)
    except ValueError as exc:
        LOGGER.debug("order_submission_rejected", exc_info=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except EngineUnavailableError as exc:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "message": str(exc),
                "hint": "Install nautilus-trader or enable AMAD_USE_MOCK.",
            },
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        LOGGER.exception("order_submission_failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Order submission failed") from exc

    summary = response.get("order")
    if not isinstance(summary, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Gateway returned no order summary")
    normalised = _normalise_order_summary(summary)

    try:
        await _upsert_engine_order(session, normalised)
        await session.commit()
    except Exception:  # pragma: no cover - defensive guard
        await session.rollback()
        LOGGER.exception("order_persistence_failed")

    orders = await _load_orders(
        session,
        select(EngineOrder).where(EngineOrder.order_id == normalised.get("order_id")).limit(1),
    )
    if orders:
        return OrderResponse(order=orders[0])
    fallback = OrderResource(
        order_id=normalised.get("order_id"),
        client_order_id=normalised.get("client_order_id"),
        venue_order_id=normalised.get("venue_order_id"),
        symbol=normalised.get("symbol"),
        venue=normalised.get("venue"),
        side=normalised.get("side"),
        type=normalised.get("type"),
        quantity=_coerce_float(normalised.get("quantity")),
        filled_quantity=_coerce_float(normalised.get("filled_quantity")),
        price=_coerce_float(normalised.get("price")),
        average_price=_coerce_float(normalised.get("average_price")),
        status=normalised.get("status"),
        time_in_force=normalised.get("time_in_force"),
        expire_time=normalised.get("expire_time"),
        post_only=normalised.get("post_only"),
        reduce_only=normalised.get("reduce_only"),
        limit_offset=_coerce_float(normalised.get("limit_offset")),
        contingency_type=normalised.get("contingency_type"),
        order_list_id=normalised.get("order_list_id"),
        linked_order_ids=list(normalised.get("linked_order_ids") or []),
        parent_order_id=normalised.get("parent_order_id"),
        node_id=normalised.get("node_id"),
        instructions=normalised.get("instructions"),
        created_at=_parse_timestamp(normalised.get("created_at")),
        updated_at=_parse_timestamp(normalised.get("updated_at")),
    )
    return OrderResponse(order=fallback)


@router.delete("/{order_id}", response_model=OrderResponse)
async def cancel_order(order_id: str, session: AsyncSession = Depends(get_session)) -> OrderResponse:
    try:
        svc.require_engine()
    except EngineUnavailableError as exc:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "message": str(exc),
                "hint": "Install nautilus-trader or enable AMAD_USE_MOCK.",
            },
        ) from exc
    try:
        response = svc.cancel_order(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EngineUnavailableError as exc:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "message": str(exc),
                "hint": "Install nautilus-trader or enable AMAD_USE_MOCK.",
            },
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        LOGGER.exception("order_cancel_failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Order cancel failed") from exc

    summary = response.get("order")
    if not isinstance(summary, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Gateway returned no order summary")
    normalised = _normalise_order_summary(summary)

    try:
        await _upsert_engine_order(session, normalised)
        await session.commit()
    except Exception:  # pragma: no cover - defensive guard
        await session.rollback()
        LOGGER.exception("order_cancel_persistence_failed")

    orders = await _load_orders(
        session,
        select(EngineOrder).where(EngineOrder.order_id == order_id).limit(1),
    )
    if orders:
        return OrderResponse(order=orders[0])
    fallback = OrderResource(
        order_id=normalised.get("order_id"),
        client_order_id=normalised.get("client_order_id"),
        venue_order_id=normalised.get("venue_order_id"),
        symbol=normalised.get("symbol"),
        venue=normalised.get("venue"),
        side=normalised.get("side"),
        type=normalised.get("type"),
        quantity=_coerce_float(normalised.get("quantity")),
        filled_quantity=_coerce_float(normalised.get("filled_quantity")),
        price=_coerce_float(normalised.get("price")),
        average_price=_coerce_float(normalised.get("average_price")),
        status=normalised.get("status"),
        time_in_force=normalised.get("time_in_force"),
        expire_time=normalised.get("expire_time"),
        post_only=normalised.get("post_only"),
        reduce_only=normalised.get("reduce_only"),
        limit_offset=_coerce_float(normalised.get("limit_offset")),
        contingency_type=normalised.get("contingency_type"),
        order_list_id=normalised.get("order_list_id"),
        linked_order_ids=list(normalised.get("linked_order_ids") or []),
        parent_order_id=normalised.get("parent_order_id"),
        node_id=normalised.get("node_id"),
        instructions=normalised.get("instructions"),
        created_at=_parse_timestamp(normalised.get("created_at")),
        updated_at=_parse_timestamp(normalised.get("updated_at")),
    )
    return OrderResponse(order=fallback)


@router.post(
    "/{order_id}/duplicate",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_order(order_id: str, session: AsyncSession = Depends(get_session)) -> OrderResponse:
    try:
        svc.require_engine()
    except EngineUnavailableError as exc:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "message": str(exc),
                "hint": "Install nautilus-trader or enable AMAD_USE_MOCK.",
            },
        ) from exc

    try:
        response = svc.duplicate_order(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EngineUnavailableError as exc:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "message": str(exc),
                "hint": "Install nautilus-trader or enable AMAD_USE_MOCK.",
            },
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        LOGGER.exception("order_duplicate_failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Order duplicate failed") from exc

    summary = response.get("order")
    if not isinstance(summary, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Gateway returned no order summary")

    normalised = _normalise_order_summary(summary)

    try:
        await _upsert_engine_order(session, normalised)
        await session.commit()
    except Exception:  # pragma: no cover - defensive guard
        await session.rollback()
        LOGGER.exception("order_duplicate_persistence_failed")

    orders = await _load_orders(
        session,
        select(EngineOrder).where(EngineOrder.order_id == normalised.get("order_id")).limit(1),
    )
    if orders:
        return OrderResponse(order=orders[0])

    fallback = OrderResource(
        order_id=normalised.get("order_id"),
        client_order_id=normalised.get("client_order_id"),
        venue_order_id=normalised.get("venue_order_id"),
        symbol=normalised.get("symbol"),
        venue=normalised.get("venue"),
        side=normalised.get("side"),
        type=normalised.get("type"),
        quantity=_coerce_float(normalised.get("quantity")),
        filled_quantity=_coerce_float(normalised.get("filled_quantity")),
        price=_coerce_float(normalised.get("price")),
        average_price=_coerce_float(normalised.get("average_price")),
        status=normalised.get("status"),
        time_in_force=normalised.get("time_in_force"),
        expire_time=normalised.get("expire_time"),
        post_only=normalised.get("post_only"),
        reduce_only=normalised.get("reduce_only"),
        limit_offset=_coerce_float(normalised.get("limit_offset")),
        contingency_type=normalised.get("contingency_type"),
        order_list_id=normalised.get("order_list_id"),
        linked_order_ids=list(normalised.get("linked_order_ids") or []),
        parent_order_id=normalised.get("parent_order_id"),
        node_id=normalised.get("node_id"),
        instructions=normalised.get("instructions"),
        created_at=_parse_timestamp(normalised.get("created_at")),
        updated_at=_parse_timestamp(normalised.get("updated_at")),
    )
    return OrderResponse(order=fallback)
