"""Shared test fixtures and configuration.

Provides:
- FastAPI test client (async)
- Settings override to use SQLite for tests
- Database session fixtures
"""

import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest

# Ensure all models are imported so Base.metadata is populated
from httpx import ASGITransport, AsyncClient

# Set test environment BEFORE importing app modules
os.environ["TRADING_MODE"] = "BACKTEST"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = ""
os.environ["LOG_FORMAT"] = "console"
os.environ["LOG_LEVEL"] = "DEBUG"


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Clear the cached settings before each test so env overrides take effect."""
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async test client for the FastAPI application.

    Patches database health check to return True (no real DB in unit tests).
    """
    from app.main import create_app

    app = create_app()

    with patch("app.api.health.check_database_health", new_callable=AsyncMock, return_value=True):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as ac:
            yield ac


