"""Market data routes exposing instrument metadata and live streams."""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, WebSocket
from fastapi.websockets import WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

from ..nautilus_service import svc

router = APIRouter(tags=["market"])


class InstrumentResource(BaseModel):
    """Serialised representation of an instrument description."""

    instrument_id: str
    symbol: str
    venue: str
    type: str
    base_currency: str | None = None
    quote_currency: str | None = None
    tick_size: float | None = None
    lot_size: float | None = None
    contract_size: float | None = None
    min_notional: float | None = None
    expiry: str | None = None

    model_config = ConfigDict(extra="allow")


class InstrumentListResponse(BaseModel):
    instruments: list[InstrumentResource]


class WatchlistUpdate(BaseModel):
    favorites: list[str] = Field(default_factory=list)


class WatchlistResponse(BaseModel):
    favorites: list[str] = Field(default_factory=list)


class HistoricalBarSample(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class HistoricalBarsResponse(BaseModel):
    instrument_id: str
    granularity: str
    bars: list[HistoricalBarSample]


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_topic(base: str, instrument_id: str | None) -> str:
    if instrument_id:
        return f"{base}.{instrument_id}"
    return base


async def _stream_bus_topic(websocket: WebSocket, topic: str) -> None:
    server_loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop_event = asyncio.Event()

    async def pump_bus_messages() -> None:
        try:
            async with svc.bus.subscribe(topic) as subscription:
                async for payload in subscription:
                    if stop_event.is_set():
                        break
                    if payload is None:
                        continue
                    try:
                        server_loop.call_soon_threadsafe(
                            queue.put_nowait, payload
                        )
                    except Exception:
                        break
        finally:
            server_loop.call_soon_threadsafe(queue.put_nowait, None)

    bus_future = asyncio.run_coroutine_threadsafe(
        pump_bus_messages(), svc.bus.loop
    )

    await websocket.accept()
    try:
        while True:
            payload = await queue.get()
            if payload is None:
                break
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        stop_event.set()
        bus_future.cancel()
        with contextlib.suppress(Exception):
            bus_future.result()


@router.get("/market/instruments", response_model=InstrumentListResponse)
async def list_instruments(venue: str | None = Query(default=None, min_length=1)) -> InstrumentListResponse:
    payload = svc.list_instruments(venue=venue)
    return InstrumentListResponse.model_validate(payload)


@router.get("/market/watchlist", response_model=WatchlistResponse)
async def get_watchlist() -> WatchlistResponse:
    payload = svc.get_watchlist()
    return WatchlistResponse.model_validate(payload)


@router.put("/market/watchlist", response_model=WatchlistResponse)
async def update_watchlist(update: WatchlistUpdate) -> WatchlistResponse:
    payload = svc.update_watchlist(update.favorites)
    return WatchlistResponse.model_validate(payload)


@router.get(
    "/market/instruments/{instrument_id}/bars",
    response_model=HistoricalBarsResponse,
)
async def get_historical_bars(
    instrument_id: str,
    granularity: str = Query(pattern=r"^\d+[mhdw]$", min_length=2, max_length=6),
    limit: int | None = Query(default=None, ge=1, le=1000),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
) -> HistoricalBarsResponse:
    try:
        payload = svc.get_historical_bars(
            instrument_id=instrument_id,
            granularity=granularity,
            limit=limit,
            start=_format_datetime(start),
            end=_format_datetime(end),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return HistoricalBarsResponse.model_validate(payload)


@router.websocket("/ws/market/depth")
async def market_depth_stream(websocket: WebSocket) -> None:
    instrument_id = websocket.query_params.get("instrument_id")
    topic = _build_topic("market.depth", instrument_id)
    await _stream_bus_topic(websocket, topic)


@router.websocket("/ws/market/trades")
async def market_trades_stream(websocket: WebSocket) -> None:
    instrument_id = websocket.query_params.get("instrument_id")
    topic = _build_topic("market.trades", instrument_id)
    await _stream_bus_topic(websocket, topic)


@router.websocket("/ws/market/ticks")
async def market_ticks_stream(websocket: WebSocket) -> None:
    instrument_id = websocket.query_params.get("instrument_id")
    topic = _build_topic("market.ticks", instrument_id)
    await _stream_bus_topic(websocket, topic)
