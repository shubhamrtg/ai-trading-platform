"""Tests for the read-only Strategy API endpoints (Phase J)."""

import pytest
from app.database import get_db
from app.main import create_app
from app.models.base import Base
from app.models.enums import StrategyStatus
from app.models.strategy import StrategyModel, StrategyVersionModel
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


from collections.abc import AsyncGenerator

@pytest.fixture
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    """Create an async in-memory SQLite database for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def seeded_db(test_db: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    """Seed the database with test strategies and versions."""
    strategy = StrategyModel(
        strategy_id="sma_crossover",
        name="SMA Crossover",
        description="Simple moving average crossover strategy",
        author="test",
        status=StrategyStatus.ACTIVE,
    )
    test_db.add(strategy)
    await test_db.flush()

    version1 = StrategyVersionModel(
        strategy_id="sma_crossover",
        version="1.0.0",
        status=StrategyStatus.ACTIVE,
        source_hash="abc123",
        supported_timeframes=["1h", "4h"],
        supported_asset_classes=["crypto"],
        required_indicators=["SMA"],
        parameters_schema={"fast_period": 10, "slow_period": 20},
    )
    version2 = StrategyVersionModel(
        strategy_id="sma_crossover",
        version="2.0.0",
        status=StrategyStatus.DRAFT,
        supported_timeframes=["1h"],
    )
    test_db.add_all([version1, version2])
    await test_db.commit()

    yield test_db


@pytest.fixture
async def client(seeded_db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with the seeded database."""
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_strategies_returns_strategies(client: AsyncClient) -> None:
    """GET /api/v1/strategies returns a list of strategies."""
    response = await client.get("/api/v1/strategies")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["strategy_id"] == "sma_crossover"
    assert data[0]["name"] == "SMA Crossover"
    assert data[0]["status"] == "ACTIVE"
    assert data[0]["version_count"] == 2


@pytest.mark.asyncio
async def test_list_strategies_empty(test_db: AsyncSession) -> None:
    """GET /api/v1/strategies returns empty list when no strategies exist."""
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/strategies")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_strategy_detail(client: AsyncClient) -> None:
    """GET /api/v1/strategies/{id} returns strategy with versions."""
    response = await client.get("/api/v1/strategies/sma_crossover")
    assert response.status_code == 200
    data = response.json()
    assert data["strategy_id"] == "sma_crossover"
    assert data["name"] == "SMA Crossover"
    assert data["description"] == "Simple moving average crossover strategy"
    assert len(data["versions"]) == 2

    # Verify version details
    versions_by_ver = {v["version"]: v for v in data["versions"]}
    v1 = versions_by_ver["1.0.0"]
    assert v1["status"] == "ACTIVE"
    assert v1["source_hash"] == "abc123"
    assert v1["supported_timeframes"] == ["1h", "4h"]
    assert v1["parameters_schema"] == {"fast_period": 10, "slow_period": 20}

    v2 = versions_by_ver["2.0.0"]
    assert v2["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_get_strategy_not_found(client: AsyncClient) -> None:
    """GET /api/v1/strategies/{id} returns 404 for nonexistent strategy."""
    response = await client.get("/api/v1/strategies/nonexistent")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
