"""Tests for the Phase D Backtesting Engine."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from collections.abc import AsyncGenerator
from app.backtesting.engine import BacktestEngine
from app.backtesting.schemas import BacktestRequest
from app.models.enums import BacktestStatus, OrderSide, StrategyStatus
from app.schemas.market_data import Candle
from app.strategies.repository import StrategyVersionRepository
from app.strategies.service import StrategyExecutionService
from sqlalchemy.ext.asyncio import AsyncSession

UTC = UTC


# Small deterministic candle sequences for hand-calculated tests
def create_candles() -> list[Candle]:
    """
    Candles for MACrossover strategy test (fast=2, slow=3):
    Need at least 3 candles to initialize.
    """
    return [
        Candle(
            symbol="BTC-USD",
            timeframe="1d",
            timestamp=datetime(2023, 1, 1, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("100"),
            volume=Decimal("10"), vwap=None, trades=None,
        ),
        Candle(
            symbol="BTC-USD",
            timeframe="1d",
            timestamp=datetime(2023, 1, 2, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("100"),
            volume=Decimal("10"), vwap=None, trades=None,
        ),
        Candle(
            symbol="BTC-USD",
            timeframe="1d",
            timestamp=datetime(2023, 1, 3, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("100"),
            volume=Decimal("10"), vwap=None, trades=None,
        ),
        # MA cross above (BULLISH)
        Candle(
            symbol="BTC-USD",
            timeframe="1d",
            timestamp=datetime(2023, 1, 4, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("130"),
            low=Decimal("90"),
            close=Decimal("120"),
            volume=Decimal("10"), vwap=None, trades=None,
        ),
        # MA cross below (BEARISH)
        Candle(
            symbol="BTC-USD",
            timeframe="1d",
            timestamp=datetime(2023, 1, 5, tzinfo=UTC),
            open=Decimal("120"),
            high=Decimal("120"),
            low=Decimal("80"),
            close=Decimal("80"),
            volume=Decimal("10"), vwap=None, trades=None,
        ),
        # Another candle to exit
        Candle(
            symbol="BTC-USD",
            timeframe="1d",
            timestamp=datetime(2023, 1, 6, tzinfo=UTC),
            open=Decimal("80"),
            high=Decimal("90"),
            low=Decimal("70"),
            close=Decimal("85"),
            volume=Decimal("10"), vwap=None, trades=None,
        ),
    ]


async def candle_generator(candles: list[Candle]) -> AsyncGenerator[Candle, None]:
    for c in candles:
        yield c


@pytest.fixture
def base_request() -> BacktestRequest:
    return BacktestRequest(
        strategy_id="MA_Crossover_Reference",
        strategy_version="1.0.0",
        symbol="BTC-USD",
        timeframe="1d",
        start_time=datetime(2023, 1, 1, tzinfo=UTC),
        end_time=datetime(2023, 1, 6, tzinfo=UTC),
        initial_capital=Decimal("100000.0"),
        commission_pct=Decimal("0.1"),
        slippage_pct=Decimal("0.1"),
        parameters={"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
    )


@pytest.mark.asyncio
async def test_backtest_successful_execution(
    db_session: AsyncSession, base_request: BacktestRequest
) -> None:
    # Setup persisted strategy from Phase C testing utilities if needed
    # We can just rely on the existing setup logic
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(
        db_session, "MA_Crossover_Reference", "1.0.0", status=StrategyStatus.ACTIVE
    )

    engine = BacktestEngine(StrategyExecutionService(StrategyVersionRepository(db_session)))
    result = await engine.run_backtest(base_request, candle_generator(create_candles()))

    assert result.status == BacktestStatus.COMPLETED
    assert result.metrics is not None
    assert result.metrics.initial_capital == Decimal("100000.0")

    # 1. Strategy evaluates Candle 4 (close 120), generates BUY.
    # 2. Simulator executes at Candle 5 open (120).
    #    Slippage 0.1% -> Price = 120 * 1.001 = 120.12
    #    Qty = 100,000 / 120.12 = 832.49...
    # 3. Strategy evaluates Candle 5 (close 80), generates SELL.
    # 4. Simulator executes at Candle 6 open (80).
    #    Slippage 0.1% -> Price = 80 * 0.999 = 79.92

    trades = result.trades
    assert len(trades) == 1
    t1 = trades[0]

    assert t1.side == OrderSide.BUY
    assert t1.entry_price == Decimal("120") * Decimal("1.001")
    assert t1.exit_price == Decimal("85")

    assert t1.entry_timestamp == datetime(2023, 1, 5, tzinfo=UTC)
    assert t1.exit_timestamp == datetime(2023, 1, 6, tzinfo=UTC)


@pytest.mark.asyncio
async def test_backtest_invalid_chronology(db_session: AsyncSession, base_request: BacktestRequest) -> None:
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")

    engine = BacktestEngine(StrategyExecutionService(StrategyVersionRepository(db_session)))

    bad_candles = create_candles()
    # Swap to make it out of order
    bad_candles[1], bad_candles[2] = bad_candles[2], bad_candles[1]

    result = await engine.run_backtest(base_request, candle_generator(bad_candles))
    assert result.status == BacktestStatus.FAILED
    assert "chronological" in (result.error_message or "")


@pytest.mark.asyncio
async def test_backtest_missing_data(db_session: AsyncSession, base_request: BacktestRequest) -> None:
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")

    engine = BacktestEngine(StrategyExecutionService(StrategyVersionRepository(db_session)))

    # Empty generator
    result = await engine.run_backtest(base_request, candle_generator([]))
    assert result.status == BacktestStatus.FAILED
    assert "No historical data provided" in (result.error_message or "")


@pytest.mark.asyncio
async def test_backtest_reproducibility(db_session: AsyncSession, base_request: BacktestRequest) -> None:
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")

    engine = BacktestEngine(StrategyExecutionService(StrategyVersionRepository(db_session)))

    result1 = await engine.run_backtest(base_request, candle_generator(create_candles()))
    result2 = await engine.run_backtest(base_request, candle_generator(create_candles()))

    assert result1.status == BacktestStatus.COMPLETED
    assert result2.status == BacktestStatus.COMPLETED

    assert result1.metrics and result2.metrics and result1.metrics.final_equity == result2.metrics.final_equity
    assert len(result1.trades) == len(result2.trades)
    assert result1.trades[0].net_pnl == result2.trades[0].net_pnl

    # Backtest IDs must differ
    assert result1.backtest_id != result2.backtest_id


@pytest.mark.asyncio
async def test_backtest_end_of_period_forced_close(
    db_session: AsyncSession, base_request: BacktestRequest
) -> None:
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")

    engine = BacktestEngine(StrategyExecutionService(StrategyVersionRepository(db_session)))

    # Only supply candles up to the BUY signal, so the position remains open
    short_candles = create_candles()[:5]
    # Candle 4 generates BUY. Candle 5 executes BUY. No Candle 6.

    result = await engine.run_backtest(base_request, candle_generator(short_candles))
    assert result.status == BacktestStatus.COMPLETED

    assert len(result.trades) == 1
    # Exit price should be Candle 5 close
    assert result.trades[0].exit_price == Decimal("80")
    assert result.trades[0].exit_timestamp == datetime(2023, 1, 5, tzinfo=UTC)
