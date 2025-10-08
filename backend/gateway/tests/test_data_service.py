from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from backend.gateway.app.data_service import DataService, HistoricalDataRequest
from backend.gateway.db.models import HistoricalDataStatus, HistoricalDataset
from backend.gateway.db.base import get_session_factory


@pytest.mark.asyncio
async def test_dataset_generation_is_deterministic(tmp_path, db_session) -> None:
    service = DataService(
        base_path=tmp_path,
        session_factory_provider=get_session_factory,
    )

    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=4)
    request = HistoricalDataRequest(
        venue="BINANCE",
        instrument="BTCUSDT",
        timeframe="1m",
        start=start,
        end=end,
    )

    summary = await service.ensure_dataset(request, run_download=True)
    assert summary.dataset.status == HistoricalDataStatus.READY

    dataset_path = service.dataset_path(request.dataset_id)
    first_contents = dataset_path.read_text(encoding="utf-8")

    dataset_path.unlink()
    await db_session.execute(
        update(HistoricalDataset)
        .where(HistoricalDataset.id == summary.dataset.id)
        .values(status=HistoricalDataStatus.PENDING, path=None, size_bytes=None, rows=None)
    )
    await db_session.commit()

    await service.download_dataset(summary.dataset.id)

    regenerated_path = service.dataset_path(request.dataset_id)
    assert regenerated_path.exists()
    second_contents = regenerated_path.read_text(encoding="utf-8")
    assert second_contents == first_contents
