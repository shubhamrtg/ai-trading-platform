"""Tests for the Phase D Backtesting Engine."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.backtesting.engine import BacktestEngine
from app.backtesting.schemas import BacktestRequest
from app.models.enums import BacktestStatus, OrderSide, StrategyStatus
from app.schemas.market_data import Candle
from app.strategies.repository import StrategyVersionRepository
from app.strategies.service import StrategyExecutionService
from sqlalchemy.ext.asyncio import AsyncSession


def create_candles() -> list[Candle]:
    """Candles for MACrossover test (fast=2, slow=3)."""
    return [
        Candle(
            symbol="BTC-USD",
            timeframe="1d",
            timestamp=datetime(2023, 1, 1, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("100"),
            volume=Decimal("10"),
            vwap=None,
            trades=None,
        ),
        Candle(
            symbol="BTC-USD",
            timeframe="1d",
            timestamp=datetime(2023, 1, 2, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("100"),
            volume=Decimal("10"),
            vwap=None,
            trades=None,
        ),
        Candle(
            symbol="BTC-USD",
            timeframe="1d",
            timestamp=datetime(2023, 1, 3, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("100"),
            volume=Decimal("10"),
            vwap=None,
            trades=None,
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
            volume=Decimal("10"),
            vwap=None,
            trades=None,
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
            volume=Decimal("10"),
            vwap=None,
            trades=None,
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
            volume=Decimal("10"),
            vwap=None,
            trades=None,
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
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(
        db_session, "MA_Crossover_Reference", "1.0.0", status=StrategyStatus.ACTIVE
    )

    engine = BacktestEngine(StrategyExecutionService(StrategyVersionRepository(db_session)))
    run = await engine.run_backtest(base_request, candle_generator(create_candles()))

    assert run.status == BacktestStatus.COMPLETED
    result = run.result
    assert result is not None
    assert result.metrics.initial_capital == Decimal("100000.0")

    trades = result.trades
    assert len(trades) == 1
    t1 = trades[0]

    assert t1.side == OrderSide.BUY

    # 1. Buy executes on Candle 5 open
    expected_entry_price = Decimal("120") * Decimal("1.001")
    assert t1.entry_price == expected_entry_price

    # Cash tracking check to prove commission logic isn't resulting in negative balance
    commission_rate = Decimal("0.001")
    # quantity = 100,000 / (120.12 * 1.001)
    expected_quantity = Decimal("100000.0") / (
        expected_entry_price * (Decimal("1") + commission_rate)
    )

    assert abs(t1.quantity - expected_quantity) < Decimal("1e-8")

    # 2. Sell executes on Candle 6 open (since signal generated on candle 5)
    expected_exit_price = Decimal("84.915")
    assert t1.exit_price == expected_exit_price

    assert t1.entry_timestamp == datetime(2023, 1, 5, tzinfo=UTC)
    assert t1.exit_timestamp == datetime(2023, 1, 6, tzinfo=UTC)


@pytest.mark.asyncio
async def test_backtest_invalid_chronology(
    db_session: AsyncSession, base_request: BacktestRequest
) -> None:
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")

    engine = BacktestEngine(StrategyExecutionService(StrategyVersionRepository(db_session)))

    bad_candles = create_candles()
    bad_candles[1], bad_candles[2] = bad_candles[2], bad_candles[1]

    run = await engine.run_backtest(base_request, candle_generator(bad_candles))
    assert run.status == BacktestStatus.FAILED
    assert "chronological" in (run.error_message or "")


@pytest.mark.asyncio
async def test_backtest_missing_data(
    db_session: AsyncSession, base_request: BacktestRequest
) -> None:
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")

    engine = BacktestEngine(StrategyExecutionService(StrategyVersionRepository(db_session)))

    run = await engine.run_backtest(base_request, candle_generator([]))
    assert run.status == BacktestStatus.FAILED
    assert "No historical data provided" in (run.error_message or "")


@pytest.mark.asyncio
async def test_backtest_reproducibility(
    db_session: AsyncSession, base_request: BacktestRequest
) -> None:
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")

    engine = BacktestEngine(StrategyExecutionService(StrategyVersionRepository(db_session)))

    run1 = await engine.run_backtest(base_request, candle_generator(create_candles()))
    run2 = await engine.run_backtest(base_request, candle_generator(create_candles()))

    assert run1.status == BacktestStatus.COMPLETED
    assert run2.status == BacktestStatus.COMPLETED

    assert run1.result is not None and run2.result is not None
    # Deterministic equality test, unaffected by runtime UUIDs
    assert run1.result == run2.result

    # Run UUIDs differ
    assert run1.run_id != run2.run_id


@pytest.mark.asyncio
async def test_backtest_end_of_period_forced_close_and_equity_match(
    db_session: AsyncSession, base_request: BacktestRequest
) -> None:
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")

    engine = BacktestEngine(StrategyExecutionService(StrategyVersionRepository(db_session)))

    # Only supply candles up to the BUY signal, so the position remains open
    short_candles = create_candles()[:5]

    run = await engine.run_backtest(base_request, candle_generator(short_candles))
    assert run.status == BacktestStatus.COMPLETED

    result = run.result
    assert result is not None

    assert len(result.trades) == 1
    # Exit price should be Candle 5 close because forced exit happens using candle close
    # Slippage is 0.1%. So exit fill price = 80 - 0.08 = 79.92
    assert result.trades[0].exit_price == Decimal("79.92")
    assert result.trades[0].exit_timestamp == datetime(2023, 1, 5, tzinfo=UTC)

    # Validate final equity matches equity curve point
    final_equity_curve_point = result.equity_curve[-1]
    assert result.metrics.final_equity == final_equity_curve_point.equity


@pytest.mark.asyncio
async def test_backtest_time_window_enforcement(
    db_session: AsyncSession, base_request: BacktestRequest
) -> None:
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")

    engine = BacktestEngine(StrategyExecutionService(StrategyVersionRepository(db_session)))

    # 1. start_time > end_time should fail
    bad_req1 = base_request.model_copy(update={"start_time": datetime(2023, 1, 10, tzinfo=UTC)})
    run1 = await engine.run_backtest(bad_req1, candle_generator(create_candles()))
    assert run1.status == BacktestStatus.FAILED
    assert "start_time must be strictly before end_time" in (run1.error_message or "")

    # 2. candle before start_time should fail
    bad_req2 = base_request.model_copy(update={"start_time": datetime(2023, 1, 2, tzinfo=UTC)})
    run2 = await engine.run_backtest(bad_req2, candle_generator(create_candles()))
    assert run2.status == BacktestStatus.FAILED
    assert "Candle timestamp is outside requested window" in (run2.error_message or "")

    # 3. candle after end_time should fail
    bad_req3 = base_request.model_copy(update={"end_time": datetime(2023, 1, 5, tzinfo=UTC)})
    run3 = await engine.run_backtest(bad_req3, candle_generator(create_candles()))
    assert run3.status == BacktestStatus.FAILED
    assert "Candle timestamp is outside requested window" in (run3.error_message or "")

    # 4. exact start/end boundary should succeed
    exact_req = base_request.model_copy(
        update={
            "start_time": datetime(2023, 1, 1, tzinfo=UTC),
            "end_time": datetime(2023, 1, 6, tzinfo=UTC),
        }
    )
    run_exact = await engine.run_backtest(exact_req, candle_generator(create_candles()))
    assert run_exact.status == BacktestStatus.COMPLETED


@pytest.mark.asyncio
async def test_zero_vs_high_commission(
    db_session: AsyncSession, base_request: BacktestRequest
) -> None:
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")

    engine = BacktestEngine(StrategyExecutionService(StrategyVersionRepository(db_session)))

    # Zero commission
    req_zero = base_request.model_copy(
        update={"commission_pct": Decimal("0.0"), "slippage_pct": Decimal("0.0")}
    )
    run_zero = await engine.run_backtest(req_zero, candle_generator(create_candles()))

    # High commission (50% commission!)
    req_high = base_request.model_copy(
        update={"commission_pct": Decimal("50.0"), "slippage_pct": Decimal("0.0")}
    )
    run_high = await engine.run_backtest(req_high, candle_generator(create_candles()))

    res_zero = run_zero.result
    res_high = run_high.result
    assert res_zero is not None and res_high is not None

    trade_zero = res_zero.trades[0]
    trade_high = res_high.trades[0]

    # Quantity with zero commission should be exactly initial_capital / fill_price
    # 100000 / 120 = 833.333...
    expected_qty_zero = Decimal("100000.0") / Decimal("120")
    assert abs(trade_zero.quantity - expected_qty_zero) < Decimal("1e-8")

    # Quantity with 50% commission should be initial_capital / (fill_price * 1.5)
    # 100000 / (120 * 1.5) = 100000 / 180 = 555.555...
    expected_qty_high = Decimal("100000.0") / (Decimal("120") * Decimal("1.5"))
    assert abs(trade_high.quantity - expected_qty_high) < Decimal("1e-8")

    # Verify no negative cash anywhere in the equity curve
    for pt in res_high.equity_curve:
        assert pt.cash >= Decimal("0.0")


@pytest.mark.asyncio
async def test_final_candle_signal_ignored(
    db_session: AsyncSession, base_request: BacktestRequest
) -> None:
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")

    engine = BacktestEngine(StrategyExecutionService(StrategyVersionRepository(db_session)))

    # Candles 1-4. Candle 4 creates a BUY signal.
    # Because it is the final candle, it has no next candle open to execute.
    short_candles = create_candles()[:4]

    # Edit the request window so it doesn't fail the window check
    req = base_request.model_copy(update={"end_time": datetime(2023, 1, 4, tzinfo=UTC)})

    run = await engine.run_backtest(req, candle_generator(short_candles))
    assert run.status == BacktestStatus.COMPLETED

    res = run.result
    assert res is not None

    # Zero trades because the signal generated at the end couldn't execute!
    assert len(res.trades) == 0


@pytest.mark.asyncio
async def test_accounting_golden_test(
    db_session: AsyncSession, base_request: BacktestRequest
) -> None:
    from tests.test_strategy_sdk import setup_persisted_version

    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")
    engine = BacktestEngine(StrategyExecutionService(StrategyVersionRepository(db_session)))

    # Force simple numbers
    # Initial capital = 10,000
    # Commission = 1%
    # Slippage = 1%
    req = base_request.model_copy(
        update={
            "initial_capital": Decimal("10000.0"),
            "commission_pct": Decimal("1.0"),
            "slippage_pct": Decimal("1.0"),
        }
    )

    # We will use exactly 3 candles to force a buy and force close it.
    # Candle 1: initialize (100)
    # Candle 2: initialize (100) -> MA cross above -> BUY on Candle 3 open.
    # Candle 3: Open = 100 (BUY happens here). Close = 110 (Forced SELL happens here).
    candles = [
        Candle(
            symbol="BTC-USD",
            timeframe="1d",
            timestamp=datetime(2023, 1, 1, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=Decimal("10"),
            vwap=None,
            trades=None,
        ),
        Candle(
            symbol="BTC-USD",
            timeframe="1d",
            timestamp=datetime(2023, 1, 2, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=Decimal("10"),
            vwap=None,
            trades=None,
        ),
        Candle(
            symbol="BTC-USD",
            timeframe="1d",
            timestamp=datetime(2023, 1, 3, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=Decimal("10"),
            vwap=None,
            trades=None,
        ),
        Candle(
            symbol="BTC-USD",
            timeframe="1d",
            timestamp=datetime(2023, 1, 4, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("110"),
            volume=Decimal("10"),
            vwap=None,
            trades=None,
        ),
        Candle(
            symbol="BTC-USD",
            timeframe="1d",
            timestamp=datetime(2023, 1, 5, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("110"),
            volume=Decimal("10"),
            vwap=None,
            trades=None,
        ),
    ]

    # Let's adjust req to only expect up to day 5
    req = req.model_copy(update={"end_time": datetime(2023, 1, 5, tzinfo=UTC)})

    run = await engine.run_backtest(req, candle_generator(candles))
    assert run.status == BacktestStatus.COMPLETED
    assert run.result is not None
    trade = run.result.trades[0]

    # --- HAND CALCULATED EXPECTATIONS ---
    # Entry market price = Candle 3 open = 100
    # Entry slippage = 1% of 100 = 1
    # Entry fill price = 100 + 1 = 101
    expected_entry_fill = Decimal("101.0")
    assert trade.entry_price == expected_entry_fill

    # Quantity calculation
    # cash = 10000
    # fill = 101
    # commission_rate = 0.01
    # quantity = 10000 / (101 * 1.01) = 10000 / 102.01 = 98.02960494069...
    expected_quantity = Decimal("10000.0") / Decimal("102.01")
    assert abs(trade.quantity - expected_quantity) < Decimal("1e-8")

    # Entry commission
    # notional = qty * 101
    # commission = notional * 0.01
    expected_entry_commission = expected_quantity * Decimal("101.0") * Decimal("0.01")

    # Exit market price = Candle 3 close = 110 (forced close)
    # Exit slippage = 1% of 110 = 1.10
    # Exit fill price = 110 - 1.10 = 108.90
    expected_exit_fill = Decimal("108.90")
    assert trade.exit_price == expected_exit_fill

    # Exit commission
    # notional = qty * 108.90
    # commission = notional * 0.01
    expected_exit_commission = expected_quantity * Decimal("108.90") * Decimal("0.01")

    # Total Commission
    expected_total_commission = expected_entry_commission + expected_exit_commission
    assert abs(trade.fees - expected_total_commission) < Decimal("1e-8")

    # Gross P&L
    # gross_pnl = (exit_fill - entry_fill) * qty = (108.90 - 101) * qty = 7.9 * qty
    expected_gross_pnl = Decimal("7.9") * expected_quantity
    assert abs(trade.gross_pnl - expected_gross_pnl) < Decimal("1e-8")

    # Total Slippage
    # entry_slippage_total = qty * 1.0
    # exit_slippage_total = qty * 1.10
    # total_slippage = qty * 2.10
    expected_total_slippage = expected_quantity * Decimal("2.10")
    assert abs(trade.slippage - expected_total_slippage) < Decimal("1e-8")

    # Net P&L
    # net_pnl = gross_pnl - total_commission
    expected_net_pnl = expected_gross_pnl - expected_total_commission
    assert abs(trade.net_pnl - expected_net_pnl) < Decimal("1e-8")

    # Final cash & equity
    # Starts 10,000.
    # Ends with 10,000 + net_pnl
    expected_final_cash = Decimal("10000.0") + expected_net_pnl
    assert abs(run.result.metrics.final_equity - expected_final_cash) < Decimal("1e-8")
    assert abs(run.result.equity_curve[-1].cash - expected_final_cash) < Decimal("1e-8")
