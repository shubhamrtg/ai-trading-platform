import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.market_data.client import HistoricalVendorClient
from app.market_data.exceptions import ChronologyError
from app.market_data.repository import CandleRepository
from app.market_data.service import MarketDataService
from app.schemas.market_data import Candle
from sqlalchemy.ext.asyncio import AsyncSession


class MockVendorClient(HistoricalVendorClient):
    def __init__(self):
        self.call_count = 0
        self.candles_to_return = []

    async def fetch_historical_candles(
        self, symbol: str, timeframe: str, start_time: datetime, end_time: datetime
    ) -> list[Candle]:
        self.call_count += 1
        return self.candles_to_return


@pytest.fixture
def repo(db_session: AsyncSession) -> CandleRepository:
    return CandleRepository(db_session)


@pytest.fixture
def vendor() -> MockVendorClient:
    return MockVendorClient()


@pytest.fixture
def service(repo: CandleRepository, vendor: MockVendorClient) -> MarketDataService:
    return MarketDataService(repo, vendor)


def make_candle(symbol: str, timestamp: datetime) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe="1d",
        timestamp=timestamp,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("1000"),
    )


@pytest.mark.asyncio
async def test_empty_cache_calls_vendor(service: MarketDataService, vendor: MockVendorClient):
    t1 = datetime(2023, 1, 1, tzinfo=UTC)
    t2 = datetime(2023, 1, 5, tzinfo=UTC)
    vendor.candles_to_return = [make_candle("BTC", t1), make_candle("BTC", t2)]

    candles = [c async for c in service.get_candles("BTC", "1d", t1, t2)]

    assert vendor.call_count == 1
    assert len(candles) == 2


@pytest.mark.asyncio
async def test_complete_cache_skips_vendor(service: MarketDataService, vendor: MockVendorClient):
    t1 = datetime(2023, 1, 1, tzinfo=UTC)
    t2 = datetime(2023, 1, 5, tzinfo=UTC)

    # First call populates cache
    vendor.candles_to_return = [make_candle("BTC", t1), make_candle("BTC", t2)]
    _ = [c async for c in service.get_candles("BTC", "1d", t1, t2)]
    assert vendor.call_count == 1

    # Second call uses cache, no vendor call
    candles = [c async for c in service.get_candles("BTC", "1d", t1, t2)]
    assert vendor.call_count == 1
    assert len(candles) == 2


@pytest.mark.asyncio
async def test_chronology_enforced(service: MarketDataService, vendor: MockVendorClient):
    t1 = datetime(2023, 1, 5, tzinfo=UTC)
    t2 = datetime(2023, 1, 1, tzinfo=UTC)  # Unordered
    vendor.candles_to_return = [make_candle("BTC", t1), make_candle("BTC", t2)]

    with pytest.raises(ChronologyError):
        _ = [c async for c in service.get_candles("BTC", "1d", t2, t1)]


@pytest.mark.asyncio
async def test_concurrent_requests_safe(service: MarketDataService, vendor: MockVendorClient):
    t1 = datetime(2023, 1, 1, tzinfo=UTC)
    t2 = datetime(2023, 1, 2, tzinfo=UTC)
    vendor.candles_to_return = [make_candle("BTC", t1), make_candle("BTC", t2)]

    # Fetch concurrently
    async def get_all():
        return [c async for c in service.get_candles("BTC", "1d", t1, t2)]

    task1 = asyncio.create_task(get_all())
    task2 = asyncio.create_task(get_all())

    results = await asyncio.gather(task1, task2)

    # Due to in-memory lock, it might only call vendor once. But even if twice, DB constraints prevent crash.
    # The requirement is that both succeed and return data.
    assert len(results[0]) == 2
    assert len(results[1]) == 2


@pytest.mark.asyncio
async def test_phase_e_integration(
    db_session, service: MarketDataService, vendor: MockVendorClient
):
    from app.backtesting.engine import BacktestEngine
    from app.backtesting.repository import BacktestRunRepository
    from app.backtesting.service import BacktestApplicationService
    from app.schemas.api_backtesting import BacktestCreateRequest
    from app.strategies.repository import StrategyVersionRepository
    from app.strategies.service import StrategyExecutionService

    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")
    await db_session.commit()

    backtest_repo = BacktestRunRepository(db_session)
    strat_repo = StrategyVersionRepository(db_session)
    strat_service = StrategyExecutionService(strat_repo)
    engine = BacktestEngine(strat_service)
    app_service = BacktestApplicationService(backtest_repo, strat_repo, engine, service)

    t1 = datetime(2023, 1, 1, tzinfo=UTC)
    t2 = datetime(2023, 1, 5, tzinfo=UTC)
    vendor.candles_to_return = [make_candle("BTC-USD", t1), make_candle("BTC-USD", t2)]

    req = BacktestCreateRequest(
        strategy_id="MA_Crossover_Reference",
        strategy_version="1.0.0",
        symbol="BTC-USD",
        timeframe="1d",
        start_time=t1,
        end_time=t2,
        initial_capital=Decimal("100000.0"),
        commission_pct=Decimal("0.0"),
        slippage_pct=Decimal("0.0"),
        parameters={"fast_period": 2, "slow_period": 3, "risk_percent": "1.0"},
    )

    run_model = await app_service.execute_backtest(req)

    from app.models.enums import BacktestStatus

    assert run_model.status == BacktestStatus.COMPLETED
    assert vendor.call_count == 1
