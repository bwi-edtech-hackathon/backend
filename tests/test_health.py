"""Smoke tests — verify the app boots and core endpoints respond."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    res = await client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["app"] == "coachai-backend"


@pytest.mark.asyncio
async def test_root(client: AsyncClient) -> None:
    res = await client.get("/")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "CoachAI Backend"
    assert "version" in body


@pytest.mark.asyncio
async def test_openapi_schema(client: AsyncClient) -> None:
    res = await client.get("/openapi.json")
    assert res.status_code == 200
    schema = res.json()
    assert schema["info"]["title"] == "CoachAI Backend"
    # Every module should register at least one path
    paths = list(schema["paths"].keys())
    assert any("/auth/register" in p for p in paths)
    assert any("/subjects" in p for p in paths)


@pytest.mark.asyncio
async def test_auth_register_validation(client: AsyncClient) -> None:
    """Invalid phone format should fail with 422."""
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "phone": "1234",
            "password": "shortpw1",
            "full_name": "X",
        },
    )
    # Pydantic returns 422 for body validation errors
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_protected_route_requires_auth(client: AsyncClient) -> None:
    res = await client.get("/api/v1/users/me")
    assert res.status_code == 401
