from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_list_available_exchanges(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/integrations/exchanges")
    assert response.status_code == 200
    payload = response.json()
    assert "exchanges" in payload
    assert isinstance(payload["exchanges"], list)
