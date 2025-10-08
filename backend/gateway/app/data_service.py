"""Utility helpers for managing cached historical market data."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Coroutine, Dict, Iterable, Optional, Tuple, TypeVar

import threading

from pydantic import BaseModel, Field, validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import settings
from .logging import get_logger
from gateway.db.base import get_session_factory
from gateway.db.models import BacktestResult, HistoricalDataStatus, HistoricalDataset


T = TypeVar("T")


logger = get_logger("gateway.data")


class HistoricalDataError(RuntimeError):
    """Base class for historical data provisioning errors."""


class HistoricalDataUnavailable(HistoricalDataError):
    """Raised when requested data cannot be prepared."""


class HistoricalDataRequest(BaseModel):
    """Input payload describing a historical data requirement."""

    venue: str = Field(min_length=1)
    instrument: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    start: datetime
    end: datetime
    source: str = Field(default="mock")
    label: Optional[str] = None

    @validator("start", "end", pre=True)
    @classmethod
    def _ensure_datetime(cls, value: Any) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        text = str(value)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @validator("end")
    @classmethod
    def _validate_range(cls, value: datetime, values: Dict[str, Any]) -> datetime:
        start = values.get("start")
        if isinstance(start, datetime) and value <= start:
            raise ValueError("End timestamp must be greater than start timestamp")
        return value

    @property
    def fingerprint(self) -> str:
        payload = f"{self.venue}|{self.instrument}|{self.timeframe}|{self.start.isoformat()}|{self.end.isoformat()}"
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
        return digest

    @property
    def dataset_id(self) -> str:
        return (
            f"{self.venue.lower()}-{self.instrument.lower()}-{self.timeframe}-"
            f"{self.start:%Y%m%d}-{self.end:%Y%m%d}"
        )


def _parse_timeframe(value: str) -> timedelta:
    text = value.strip().lower()
    if not text:
        raise ValueError("Timeframe cannot be empty")
    unit = text[-1]
    amount = int(text[:-1] or 1)
    if unit == "s":
        return timedelta(seconds=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    raise ValueError(f"Unsupported timeframe unit '{unit}'")


@dataclass(slots=True)
class DatasetSummary:
    dataset: HistoricalDataset
    created: bool


class DataService:
    """Coordinates historical data downloads and persistence."""

    def __init__(
        self,
        *,
        base_path: Path,
        session_factory_provider: Callable[[], async_sessionmaker[AsyncSession]],
    ) -> None:
        self._base_path = base_path
        self._base_path.mkdir(parents=True, exist_ok=True)
        self._session_factory_provider = session_factory_provider
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop_runner, name="historical-data", daemon=True
        )
        self._thread.start()

    def _get_session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            self._session_factory = self._session_factory_provider()
        return self._session_factory

    def _loop_runner(self) -> None:  # pragma: no cover - infrastructure
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_blocking(self, coro: Coroutine[Any, Any, T]) -> T:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        factory = self._get_session_factory()
        async with factory() as session:
            yield session

    def dataset_path(self, dataset_id: str) -> Path:
        return self._base_path / f"{dataset_id}.csv"

    def _create_rng(self, request: HistoricalDataRequest) -> random.Random:
        """Return a deterministic random number generator for a request."""

        seed_material = f"{request.fingerprint}|{request.source or 'mock'}"
        digest = hashlib.sha256(seed_material.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:16], "big", signed=False)
        return random.Random(seed)

    async def _find_dataset(self, session: AsyncSession, fingerprint: str) -> Optional[HistoricalDataset]:
        result = await session.execute(
            select(HistoricalDataset).where(HistoricalDataset.fingerprint == fingerprint)
        )
        return result.scalars().first()

    async def _create_dataset_record(
        self, session: AsyncSession, request: HistoricalDataRequest
    ) -> HistoricalDataset:
        dataset = HistoricalDataset(
            dataset_id=request.dataset_id,
            fingerprint=request.fingerprint,
            venue=request.venue.upper(),
            instrument=request.instrument.upper(),
            timeframe=request.timeframe,
            date_from=request.start,
            date_to=request.end,
            status=HistoricalDataStatus.PENDING,
            source=request.source,
            parameters={
                "label": request.label,
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
                "instrument": request.instrument,
                "venue": request.venue,
                "timeframe": request.timeframe,
            },
        )
        session.add(dataset)
        await session.flush()
        return dataset

    async def ensure_dataset(
        self,
        request: HistoricalDataRequest,
        *,
        run_download: bool = False,
    ) -> DatasetSummary:
        async with self._session() as session:
            existing = await self._find_dataset(session, request.fingerprint)
            created = False
            if existing is None:
                existing = await self._create_dataset_record(session, request)
                created = True
            elif existing.status == HistoricalDataStatus.FAILED:
                existing.status = HistoricalDataStatus.PENDING
                existing.error = None
                existing.updated_at = datetime.now(tz=UTC)
            await session.commit()
            dataset_id = existing.id

        if run_download:
            await self.download_dataset(dataset_id)

        async with self._session() as session:
            record = await session.get(HistoricalDataset, dataset_id)
            if record is None:
                raise HistoricalDataUnavailable("Dataset record disappeared during provisioning")
            return DatasetSummary(dataset=record, created=created)

    async def download_dataset(self, dataset_pk: int) -> None:
        async with self._session() as session:
            dataset = await session.get(HistoricalDataset, dataset_pk, with_for_update=True)
            if dataset is None:
                raise HistoricalDataUnavailable("Dataset not found")
            request = HistoricalDataRequest(
                venue=dataset.venue,
                instrument=dataset.instrument,
                timeframe=dataset.timeframe,
                start=dataset.date_from,
                end=dataset.date_to,
                source=dataset.source or "mock",
                label=dataset.parameters.get("label"),
            )
            if dataset.status == HistoricalDataStatus.READY and dataset.path:
                logger.debug("dataset_cached", dataset_id=dataset.dataset_id)
                return
            dataset.status = HistoricalDataStatus.RUNNING
            dataset.error = None
            dataset.updated_at = datetime.now(tz=UTC)
            await session.commit()

        try:
            rows, size = await self._generate_dataset(request)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("dataset_generation_failed", dataset_id=request.dataset_id)
            async with self._session() as session:
                await session.execute(
                    update(HistoricalDataset)
                    .where(HistoricalDataset.id == dataset_pk)
                    .values(
                        status=HistoricalDataStatus.FAILED,
                        error=str(exc),
                        updated_at=datetime.now(tz=UTC),
                    )
                )
                await session.commit()
            raise HistoricalDataUnavailable(str(exc)) from exc

        async with self._session() as session:
            await session.execute(
                update(HistoricalDataset)
                .where(HistoricalDataset.id == dataset_pk)
                .values(
                    status=HistoricalDataStatus.READY,
                    path=str(self.dataset_path(request.dataset_id)),
                    rows=rows,
                    size_bytes=size,
                    completed_at=datetime.now(tz=UTC),
                    updated_at=datetime.now(tz=UTC),
                )
            )
            await session.commit()

    async def _generate_dataset(self, request: HistoricalDataRequest) -> Tuple[int, int]:
        delta = _parse_timeframe(request.timeframe)
        total_seconds = (request.end - request.start).total_seconds()
        step_seconds = max(delta.total_seconds(), 1.0)
        steps = max(1, int(total_seconds / step_seconds))
        max_rows = 50_000
        if steps > max_rows:
            factor = steps / max_rows
            delta = timedelta(seconds=step_seconds * factor)
            steps = max_rows

        path = self.dataset_path(request.dataset_id)
        rng = self._create_rng(request)
        base_price = rng.uniform(50, 500)
        timestamp = request.start
        rows_written = 0
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            price = base_price
            for _ in range(steps + 1):
                change = rng.uniform(-0.75, 0.75)
                open_price = price
                close_price = max(0.1, price + change)
                high_price = max(open_price, close_price) + rng.uniform(0, 0.5)
                low_price = min(open_price, close_price) - rng.uniform(0, 0.5)
                volume = max(0.01, abs(change) * rng.uniform(50, 200))
                writer.writerow(
                    [
                        timestamp.isoformat(),
                        round(open_price, 5),
                        round(high_price, 5),
                        round(low_price, 5),
                        round(close_price, 5),
                        round(volume, 5),
                    ]
                )
                rows_written += 1
                price = close_price
                timestamp += delta
                if timestamp >= request.end:
                    break
        size_bytes = path.stat().st_size
        logger.debug(
            "dataset_generated",
            dataset_id=request.dataset_id,
            rows=rows_written,
            size=size_bytes,
        )
        return rows_written, size_bytes

    async def list_datasets(self) -> Iterable[HistoricalDataset]:
        async with self._session() as session:
            result = await session.execute(
                select(HistoricalDataset).order_by(HistoricalDataset.created_at.desc())
            )
            return result.scalars().all()

    async def get_dataset(self, identifier: str | int) -> Optional[HistoricalDataset]:
        async with self._session() as session:
            if isinstance(identifier, int):
                return await session.get(HistoricalDataset, identifier)
            result = await session.execute(
                select(HistoricalDataset).where(HistoricalDataset.dataset_id == identifier)
            )
            return result.scalars().first()

    def ensure_backtest_dataset_sync(self, config: Dict[str, Any]) -> HistoricalDataset:
        return self._run_blocking(self.ensure_backtest_dataset(config))

    def download_dataset_sync(self, dataset_pk: int) -> None:
        self._run_blocking(self.download_dataset(dataset_pk))

    def get_dataset_sync(self, identifier: str | int) -> Optional[HistoricalDataset]:
        return self._run_blocking(self.get_dataset(identifier))

    def record_backtest_result_sync(
        self,
        *,
        node_key: str,
        dataset: Optional[HistoricalDataset],
        metrics: Dict[str, Any],
    ) -> BacktestResult:
        return self._run_blocking(
            self.record_backtest_result(node_key=node_key, dataset=dataset, metrics=metrics)
        )

    async def ensure_backtest_dataset(self, config: Dict[str, Any]) -> HistoricalDataset:
        request = self._request_from_config(config)
        summary = await self.ensure_dataset(request, run_download=True)
        if summary.dataset.status != HistoricalDataStatus.READY:
            raise HistoricalDataUnavailable("Dataset failed to prepare")
        return summary.dataset

    def _request_from_config(self, config: Dict[str, Any]) -> HistoricalDataRequest:
        sources = config.get("dataSources") or []
        data_source = next(
            (item for item in sources if (item.get("type") or "").lower() == "historical"),
            None,
        )
        if not data_source:
            raise HistoricalDataUnavailable(
                "Backtest configuration did not specify a historical data source"
            )
        params = data_source.get("parameters") or {}
        instrument = (
            params.get("instrument")
            or params.get("symbol")
            or config.get("instrument")
            or self._extract_strategy_symbol(config)
        )
        venue = params.get("venue") or data_source.get("venue") or config.get("venue")
        timeframe = params.get("barInterval") or params.get("timeframe") or params.get("granularity")
        date_range = params.get("dateRange") or config.get("dateRange")
        if not instrument or not venue or not timeframe or not date_range:
            raise HistoricalDataUnavailable("Incomplete dataset parameters supplied")
        start = date_range.get("start")
        end = date_range.get("end")
        if not start or not end:
            raise HistoricalDataUnavailable("Date range must include start and end timestamps")
        return HistoricalDataRequest(
            venue=venue,
            instrument=instrument,
            timeframe=str(timeframe),
            start=start,
            end=end,
            label=data_source.get("label"),
        )

    def _extract_strategy_symbol(self, config: Dict[str, Any]) -> Optional[str]:
        strategy = config.get("strategy") or {}
        parameters = strategy.get("parameters") or []
        for item in parameters:
            key = str(item.get("key") or "").lower()
            if key in {"symbol", "instrument", "pair"}:
                value = str(item.get("value") or "").strip().upper()
                if value:
                    return value
        return None

    async def record_backtest_result(
        self,
        *,
        node_key: str,
        dataset: Optional[HistoricalDataset],
        metrics: Dict[str, Any],
    ) -> BacktestResult:
        async with self._session() as session:
            result = await session.execute(select(BacktestResult).where(BacktestResult.node_key == node_key))
            record = result.scalars().first()
            if record is None:
                record = BacktestResult(node_key=node_key)
                session.add(record)
            if dataset:
                record.dataset_id = dataset.id
            record.started_at = metrics.get("started_at")
            record.completed_at = metrics.get("completed_at")
            record.total_return = metrics.get("total_return")
            record.sharpe_ratio = metrics.get("sharpe_ratio")
            record.max_drawdown = metrics.get("max_drawdown")
            record.metrics = metrics
            await session.commit()
            await session.refresh(record)
            return record


def build_data_service(base_path: Optional[Path] = None) -> DataService:
    resolved_path = Path(base_path or settings.data.base_path).resolve()
    return DataService(base_path=resolved_path, session_factory_provider=get_session_factory)


data_service = build_data_service()

__all__ = [
    "DataService",
    "HistoricalDataRequest",
    "HistoricalDataUnavailable",
    "build_data_service",
    "data_service",
]
