from unittest.mock import AsyncMock

import pytest

from database import get_db
from main import app

pytestmark = pytest.mark.anyio


async def test_health_with_database(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


async def test_health_without_database(client):
    db = AsyncMock()
    db.execute.side_effect = RuntimeError("private connection details")

    async def unavailable_db():
        yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = unavailable_db
    try:
        response = await client.get("/health")
    finally:
        app.dependency_overrides[get_db] = previous
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "private connection details" not in response.text
    db.execute.assert_awaited_once()
