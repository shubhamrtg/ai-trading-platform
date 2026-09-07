"""Tests for the /api/v1/system/status endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_system_status_returns_200(client: AsyncClient):
    """System status endpoint should return 200 OK."""
    response = await client.get("/api/v1/system/status")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_system_status_response_schema(client: AsyncClient):
    """System status response should contain all required fields."""
    response = await client.get("/api/v1/system/status")
    data = response.json()

    assert "app_name" in data
    assert "version" in data
    assert "trading_mode" in data
    assert "debug" in data
    assert "uptime_seconds" in data
    assert "configuration_valid" in data
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_system_status_reports_backtest_mode(client: AsyncClient):
    """System status should report BACKTEST as the trading mode."""
    response = await client.get("/api/v1/system/status")
    data = response.json()

    assert data["trading_mode"] == "BACKTEST"


@pytest.mark.asyncio
async def test_system_status_reports_version(client: AsyncClient):
    """System status should report the current version."""
    response = await client.get("/api/v1/system/status")
    data = response.json()

    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_system_status_configuration_valid(client: AsyncClient):
    """System status should report configuration as valid."""
    response = await client.get("/api/v1/system/status")
    data = response.json()

    assert data["configuration_valid"] is True


@pytest.mark.asyncio
async def test_system_status_uptime_is_positive(client: AsyncClient):
    """System uptime should be a positive number."""
    response = await client.get("/api/v1/system/status")
    data = response.json()

    assert data["uptime_seconds"] >= 0
