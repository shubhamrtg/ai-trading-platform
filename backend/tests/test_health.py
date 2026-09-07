"""Tests for the /health endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient):
    """Health endpoint should return 200 OK."""
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_response_schema(client: AsyncClient):
    """Health response should contain all required fields."""
    response = await client.get("/health")
    data = response.json()

    assert "status" in data
    assert "version" in data
    assert "trading_mode" in data
    assert "components" in data
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_health_reports_trading_mode(client: AsyncClient):
    """Health endpoint should report the current trading mode."""
    response = await client.get("/health")
    data = response.json()

    assert data["trading_mode"] == "BACKTEST"


@pytest.mark.asyncio
async def test_health_reports_version(client: AsyncClient):
    """Health endpoint should report the application version."""
    response = await client.get("/health")
    data = response.json()

    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_health_has_database_component(client: AsyncClient):
    """Health response should include database component status."""
    response = await client.get("/health")
    data = response.json()

    assert "database" in data["components"]
    assert data["components"]["database"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_overall_status_healthy(client: AsyncClient):
    """Overall status should be healthy when all components are healthy or unavailable."""
    response = await client.get("/health")
    data = response.json()

    assert data["status"] in ("healthy", "degraded")
