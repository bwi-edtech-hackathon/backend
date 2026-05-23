"""Pytest configuration — shared fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture(scope="session")
def event_loop():
    """Re-use one event loop across the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """ASGI test client — does NOT touch the DB."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
