"""REST endpoints for managing historical market data."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..data_service import (
    HistoricalDataRequest,
    HistoricalDataUnavailable,
    data_service,
)
from gateway.db.models import HistoricalDataStatus
from ..db import get_session

router = APIRouter(prefix="/data", tags=["data"])


class DatasetDto(BaseModel):
    id: int
    dataset_id: str = Field(serialization_alias="datasetId")
    venue: str
    instrument: str
    timeframe: str
    start: datetime = Field(serialization_alias="start")
    end: datetime = Field(serialization_alias="end")
    status: str
    source: Optional[str] = None
    path: Optional[str] = None
    rows: Optional[int] = None
    size_bytes: Optional[int] = Field(default=None, serialization_alias="sizeBytes")
    error: Optional[str] = None
    created_at: datetime = Field(serialization_alias="createdAt")
    completed_at: Optional[datetime] = Field(default=None, serialization_alias="completedAt")

    model_config = ConfigDict(populate_by_name=True)


class DatasetListResponse(BaseModel):
    datasets: List[DatasetDto]


class DataDownloadRequest(BaseModel):
    venue: str
    instrument: str
    timeframe: str
    start: datetime
    end: datetime
    label: Optional[str] = None
    source: Optional[str] = None


def _serialise_dataset(record) -> DatasetDto:
    return DatasetDto(
        id=record.id,
        dataset_id=record.dataset_id,
        venue=record.venue,
        instrument=record.instrument,
        timeframe=record.timeframe,
        start=record.date_from,
        end=record.date_to,
        status=record.status.value,
        source=record.source,
        path=record.path,
        rows=record.rows,
        size_bytes=record.size_bytes,
        error=record.error,
        created_at=record.created_at,
        completed_at=record.completed_at,
    )


@router.get("/datasets", response_model=DatasetListResponse)
async def list_datasets(session: AsyncSession = Depends(get_session)) -> DatasetListResponse:
    _ = session  # dependency ensures database initialised
    records = await data_service.list_datasets()
    return DatasetListResponse(datasets=[_serialise_dataset(item) for item in records])


@router.post("/download", status_code=status.HTTP_202_ACCEPTED)
async def request_dataset_download(
    payload: DataDownloadRequest,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    _ = session
    request = HistoricalDataRequest(
        venue=payload.venue,
        instrument=payload.instrument,
        timeframe=payload.timeframe,
        start=payload.start,
        end=payload.end,
        label=payload.label,
        source=payload.source or "api",
    )
    try:
        summary = await data_service.ensure_dataset(request, run_download=False)
    except HistoricalDataUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc)},
        ) from exc

    if summary.dataset.status != HistoricalDataStatus.READY:
        background.add_task(data_service.download_dataset_sync, summary.dataset.id)

    return {"dataset": _serialise_dataset(summary.dataset).model_dump(by_alias=True)}
