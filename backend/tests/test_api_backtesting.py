import datetime
from decimal import Decimal
from typing import Any

import pytest
from app.api.backtesting import get_backtest_service
from app.backtesting.engine import BacktestEngine
from app.backtesting.provider import DummyMarketDataProvider
from app.backtesting.repository import BacktestRunRepository
from app.backtesting.service import BacktestApplicationService
from app.main import create_app
from app.models.enums import BacktestStatus
from app.schemas.api_backtesting import BacktestCreateRequest
from app.strategies.repository import StrategyVersionRepository
from app.strategies.service import StrategyExecutionService
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def backtest_service(db_session: AsyncSession) -> BacktestApplicationService:
    repo = BacktestRunRepository(db_session)
    strat_repo = StrategyVersionRepository(db_session)
    strat_service = StrategyExecutionService(strat_repo)
    engine = BacktestEngine(strat_service)
    provider = DummyMarketDataProvider()
    return BacktestApplicationService(repo, strat_repo, engine, provider)


@pytest.mark.asyncio
async def test_backtest_lifecycle(
    db_session: AsyncSession,
    backtest_service: BacktestApplicationService,
) -> None:
    from tests.test_strategy_sdk import setup_persisted_version

    # Make sure we have the strategy version
    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")
    await db_session.commit()

    app = create_app()
    app.dependency_overrides[get_backtest_service] = lambda: backtest_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        req = BacktestCreateRequest(
            strategy_id="MA_Crossover_Reference",
            strategy_version="1.0.0",
            symbol="BTC-USD",
            timeframe="1d",
            start_time=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2023, 1, 10, tzinfo=datetime.UTC),
            initial_capital=Decimal("100000.0"),
            commission_pct=Decimal("0.0"),
            slippage_pct=Decimal("0.0"),
            # The service coerces numeric strings to Decimal at the application boundary
            parameters={"fast_period": 2, "slow_period": 3, "risk_percent": "1.0"},
            idempotency_key="test-key-1",
        )

        # ---- CREATE ----
        resp = await client.post("/api/v1/backtests", json=req.model_dump(mode="json"))
        assert resp.status_code == 200, resp.text
        data: dict[str, Any] = resp.json()
        run_id = data["run_id"]

        assert data["status"] == BacktestStatus.COMPLETED.value
        assert data["strategy_id"] == "MA_Crossover_Reference"
        assert data["total_trades"] is not None
        assert len(data["trades"]) > 0

        # ---- IDEMPOTENCY ----
        resp2 = await client.post("/api/v1/backtests", json=req.model_dump(mode="json"))
        assert resp2.status_code == 200
        data2: dict[str, Any] = resp2.json()
        assert data2["run_id"] == run_id  # Same key returns same run

        # ---- GET LIST ----
        resp3 = await client.get("/api/v1/backtests")
        assert resp3.status_code == 200
        list_data: dict[str, Any] = resp3.json()
        assert list_data["total"] >= 1
        assert any(item["run_id"] == run_id for item in list_data["items"])

        # ---- GET DETAIL ----
        resp4 = await client.get(f"/api/v1/backtests/{run_id}")
        assert resp4.status_code == 200
        detail_data: dict[str, Any] = resp4.json()
        assert detail_data["run_id"] == run_id
        # Decimal serialisation may produce trailing zeros; compare with Decimal
        assert Decimal(detail_data["initial_capital"]) == Decimal("100000.0")

        # ---- GET 404 ----
        resp_404 = await client.get("/api/v1/backtests/00000000-0000-0000-0000-000000000000")
        assert resp_404.status_code == 404

        # ---- FAILURE: unknown strategy → 400 ----
        # Use no idempotency key (fresh request) to avoid hitting idempotency cache
        req_fail = BacktestCreateRequest(
            strategy_id="non_existent",
            strategy_version="9.9.9",
            symbol="BTC-USD",
            timeframe="1d",
            start_time=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2023, 1, 10, tzinfo=datetime.UTC),
            parameters={"fast_period": 2, "slow_period": 3, "risk_percent": "1.0"},
            idempotency_key=None,
        )
        resp_fail = await client.post("/api/v1/backtests", json=req_fail.model_dump(mode="json"))
        assert resp_fail.status_code == 400

        app.dependency_overrides.clear()
