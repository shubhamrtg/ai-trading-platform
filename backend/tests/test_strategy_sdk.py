"""Tests for the Strategy SDK, Validation, and Execution Foundation."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.schemas.market_data import Candle
from app.schemas.signal import Signal
from app.strategies.examples.moving_average_crossover import MovingAverageCrossover
from app.strategies.runner import StrategyRunner, StrategyValidationError
from app.strategies.sdk import StrategyContext


def make_candle(close_price: str, dt: datetime) -> Candle:
    return Candle(
        symbol="BTC-USD",
        timestamp=dt,
        timeframe="1h",
        open=Decimal(close_price),
        high=Decimal(close_price),
        low=Decimal(close_price),
        close=Decimal(close_price),
        volume=Decimal("1.0"),
        vwap=None,
        trades=None,
    )


def test_strategy_metadata_is_valid() -> None:
    metadata = MovingAverageCrossover.metadata
    assert metadata.name == "MA_Crossover_Reference"
    assert metadata.version == "1.0.0"
    assert "crypto" in metadata.supported_asset_classes


def test_strategy_parameter_validation_success() -> None:
    runner = StrategyRunner(
        MovingAverageCrossover, {"fast_period": 10, "slow_period": 20, "risk_percent": "2.0"}
    )
    assert runner.parameters.fast_period == 10
    assert runner.parameters.slow_period == 20
    assert runner.parameters.risk_percent == Decimal("2.0")


def test_strategy_parameter_validation_missing() -> None:
    with pytest.raises(StrategyValidationError, match="Invalid strategy parameters"):
        StrategyRunner(
            MovingAverageCrossover,
            {"fast_period": 10},  # Missing slow_period and risk_percent
        )


def test_strategy_parameter_validation_invalid_types() -> None:
    with pytest.raises(StrategyValidationError, match="Invalid strategy parameters"):
        StrategyRunner(
            MovingAverageCrossover,
            {"fast_period": "not_an_int", "slow_period": 20, "risk_percent": "2.0"},
        )


def test_strategy_parameter_validation_cross_field() -> None:
    with pytest.raises(
        StrategyValidationError, match="slow_period must be greater than fast_period"
    ):
        StrategyRunner(
            MovingAverageCrossover, {"fast_period": 20, "slow_period": 10, "risk_percent": "2.0"}
        )


def test_strategy_parameter_validation_invalid_range() -> None:
    with pytest.raises(StrategyValidationError, match="greater than 0"):
        StrategyRunner(
            MovingAverageCrossover, {"fast_period": 0, "slow_period": 10, "risk_percent": "2.0"}
        )
    with pytest.raises(StrategyValidationError, match="less than or equal to 5"):
        StrategyRunner(
            MovingAverageCrossover, {"fast_period": 5, "slow_period": 10, "risk_percent": "6.0"}
        )


def test_strategy_execution_determinism_and_chronology() -> None:
    """Prove that exactly the same inputs yield exactly the same outputs."""

    # Run 1
    runner1 = StrategyRunner(
        MovingAverageCrossover, {"fast_period": 2, "slow_period": 3, "risk_percent": "1.0"}
    )

    # Run 2
    runner2 = StrategyRunner(
        MovingAverageCrossover, {"fast_period": 2, "slow_period": 3, "risk_percent": "1.0"}
    )

    # Construct an exact sequence of candles
    prices = ["100", "110", "90", "120", "130", "110", "90"]
    candles = [make_candle(p, datetime(2023, 1, i + 1, tzinfo=UTC)) for i, p in enumerate(prices)]

    signals1 = []
    for c in candles:
        sig = runner1.process_candle(c)
        if sig:
            signals1.append(sig)

    signals2 = []
    for c in candles:
        sig = runner2.process_candle(c)
        if sig:
            signals2.append(sig)

    # Both runs must produce identical signals at identical times with identical confidence
    assert len(signals1) == len(signals2)
    assert len(signals1) > 0

    for s1, s2 in zip(signals1, signals2, strict=True):
        assert s1.side == s2.side
        assert s1.signal_type == s2.signal_type
        assert s1.timestamp == s2.timestamp
        assert s1.strategy_id == s2.strategy_id
        assert s1.strategy_version == s2.strategy_version
        # signal_id and correlation_id will differ because they are UUIDs, which is expected.


def test_strategy_look_ahead_protection() -> None:
    """Verify that a strategy only sees the current candle and strictly past history."""
    runner = StrategyRunner(
        MovingAverageCrossover, {"fast_period": 2, "slow_period": 3, "risk_percent": "1.0"}
    )

    c1 = make_candle("100", datetime(2023, 1, 1, tzinfo=UTC))
    c2 = make_candle("110", datetime(2023, 1, 2, tzinfo=UTC))
    c3 = make_candle("90", datetime(2023, 1, 3, tzinfo=UTC))

    runner.process_candle(c1)
    # The history list inside context should only contain c1
    ctx = runner.contexts["BTC-USD_1h"]
    assert len(ctx.history) == 1
    assert ctx.history[0] == c1

    runner.process_candle(c2)
    assert len(ctx.history) == 2
    assert ctx.history[1] == c2

    # Future candles cannot exist in the context yet.
    assert c3 not in ctx.history


def test_strategy_failure_fails_closed() -> None:
    """A strategy exception should return None, not throw a system crash or invent orders."""

    # We monkey-patch the strategy's on_candle to throw an error
    class FaultyStrategy(MovingAverageCrossover):
        def on_candle(self, candle: Candle, context: StrategyContext) -> Signal | None:
            raise RuntimeError("Database connection lost! Or divide by zero!")

    runner = StrategyRunner(
        FaultyStrategy, {"fast_period": 2, "slow_period": 3, "risk_percent": "1.0"}
    )

    c = make_candle("100", datetime(2023, 1, 1, tzinfo=UTC))

    # This should be caught by the runner and fail closed (return None)
    signal = runner.process_candle(c)
    assert signal is None
