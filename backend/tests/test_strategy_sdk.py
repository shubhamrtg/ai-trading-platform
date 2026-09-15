"""Tests for the Strategy SDK, Validation, and Execution Foundation."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from app.models.enums import OrderSide
from app.schemas.market_data import Candle
from app.schemas.signal import Signal
from app.strategies.examples.moving_average_crossover import MovingAverageCrossover
from app.strategies.runner import StrategyRunner, StrategyValidationError
from app.strategies.sdk import StrategyContext, StrategyMetadata, StrategyRegistry
from pydantic import ValidationError


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
        trades=None
    )


# -------------------------------------------------------------------------------------------------
# FIX 1 & 7: Deterministic Output & Signal Contract
# -------------------------------------------------------------------------------------------------
def test_strategy_execution_determinism_and_chronology() -> None:
    """Prove that exactly the same inputs yield exactly the same outputs."""
    runner1 = StrategyRunner("MA_Crossover_Reference", "1.0.0", {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")})
    runner2 = StrategyRunner("MA_Crossover_Reference", "1.0.0", {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")})

    prices = ["100", "110", "120", "130", "110", "90", "70", "100", "150"]
    candles = [make_candle(p, datetime(2023, 1, i+1, tzinfo=UTC)) for i, p in enumerate(prices)]

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

    assert len(signals1) == len(signals2)
    assert len(signals1) > 0

    for s1, s2 in zip(signals1, signals2, strict=True):
        assert isinstance(s1, Signal)
        assert isinstance(s2, Signal)
        # Business fields are deterministic
        assert s1.side == s2.side
        assert s1.signal_type == s2.signal_type
        assert s1.timestamp == s2.timestamp
        assert s1.strategy_id == s2.strategy_id
        assert s1.strategy_version == s2.strategy_version

        # Orchestration IDs must be unique runtime generations
        assert s1.signal_id != s2.signal_id
        assert s1.correlation_id != s2.correlation_id


def test_strategy_invalid_return_type_fails_closed() -> None:
    class BadReturnStrategy(MovingAverageCrossover):
        metadata = StrategyMetadata(
            name="BadReturnStrategy",
            description="Testing",
            version="1.0.0"
        )
        def on_candle(self, candle: Candle, context: StrategyContext) -> Any:
            return {"fake": "signal"} # Invalid return type

    StrategyRegistry.register(BadReturnStrategy)

    runner = StrategyRunner("BadReturnStrategy", "1.0.0", {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")})

    # Should fail closed and return None
    assert runner.process_candle(make_candle("100", datetime(2023, 1, 1, tzinfo=UTC))) is None


# -------------------------------------------------------------------------------------------------
# FIX 2: Chronological Candle Processing
# -------------------------------------------------------------------------------------------------
def test_chronological_candle_processing() -> None:
    runner = StrategyRunner("MA_Crossover_Reference", "1.0.0", {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")})

    # Normal sequence
    c1 = make_candle("100", datetime(2023, 1, 1, 10, tzinfo=UTC))
    c2 = make_candle("110", datetime(2023, 1, 1, 11, tzinfo=UTC))
    runner.process_candle(c1)
    runner.process_candle(c2)

    assert len(runner.contexts["BTC-USD_1h"].history) == 2

    # Duplicate rejected
    runner.process_candle(c2)
    assert len(runner.contexts["BTC-USD_1h"].history) == 2

    # Out of order rejected
    c3 = make_candle("90", datetime(2023, 1, 1, 9, tzinfo=UTC))
    runner.process_candle(c3)
    assert len(runner.contexts["BTC-USD_1h"].history) == 2


# -------------------------------------------------------------------------------------------------
# FIX 3: Exact StrategyVersion Binding
# -------------------------------------------------------------------------------------------------
def test_strategy_version_binding() -> None:
    runner = StrategyRunner("MA_Crossover_Reference", "1.0.0", {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")})
    assert isinstance(runner.strategy, MovingAverageCrossover)

    with pytest.raises(StrategyValidationError, match="Unknown strategy version"):
        StrategyRunner("MA_Crossover_Reference", "2.0.0", {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")})


# -------------------------------------------------------------------------------------------------
# FIX 4: Strict Strategy Parameter Validation
# -------------------------------------------------------------------------------------------------
def test_strategy_parameter_strict_validation() -> None:
    # 1. Missing required parameter -> REJECT
    with pytest.raises(StrategyValidationError, match="Invalid strategy parameters"):
        StrategyRunner("MA_Crossover_Reference", "1.0.0", {"fast_period": 10})

    # 2. Unknown parameter -> REJECT
    with pytest.raises(StrategyValidationError, match="(?s)Invalid strategy parameters.*Extra inputs are not permitted"):
        StrategyRunner("MA_Crossover_Reference", "1.0.0", {"fast_period": 10, "slow_period": 20, "risk_percent": Decimal("2.0"), "unknown_param": 5})

    # 3. Wrong integer type -> REJECT (strict mode prevents string coercion)
    with pytest.raises(StrategyValidationError, match="(?s)Invalid strategy parameters.*Input should be a valid integer"):
        StrategyRunner("MA_Crossover_Reference", "1.0.0", {"fast_period": "20", "slow_period": 30, "risk_percent": Decimal("2.0")})


# -------------------------------------------------------------------------------------------------
# FIX 5: Immutable StrategyMetadata
# -------------------------------------------------------------------------------------------------
def test_strategy_metadata_immutability() -> None:
    metadata = StrategyMetadata(
        name="Test",
        description="Desc",
        version="1.0.0",
        supported_asset_classes=("crypto",),
        supported_timeframes=("1h",),
        required_indicators=(),
    )

    with pytest.raises(ValidationError):
        metadata.name = "Mutated"

    with pytest.raises(AttributeError):
        # Tuples have no append method
        metadata.supported_asset_classes.append("stocks") # type: ignore


# -------------------------------------------------------------------------------------------------
# FIX 6: Protect StrategyContext
# -------------------------------------------------------------------------------------------------
def test_strategy_context_protection() -> None:
    ctx = StrategyContext("Test", "1.0.0", "BTC-USD", "1h")
    c = make_candle("100", datetime(2023, 1, 1, tzinfo=UTC))
    ctx._history.append(c)

    # Strategy receives ctx.history which is a tuple
    assert isinstance(ctx.history, tuple)

    with pytest.raises(AttributeError):
        ctx.history.append(make_candle("200", datetime(2023, 1, 2, tzinfo=UTC))) # type: ignore


# -------------------------------------------------------------------------------------------------
# FIX 8 & 11: Correct MA Strategy Evaluation & Position Independence
# -------------------------------------------------------------------------------------------------
def test_ma_strategy_sufficient_history_and_position_independence() -> None:
    runner = StrategyRunner("MA_Crossover_Reference", "1.0.0", {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")})

    c1 = make_candle("100", datetime(2023, 1, 1, tzinfo=UTC))
    c2 = make_candle("100", datetime(2023, 1, 2, tzinfo=UTC))
    c3 = make_candle("100", datetime(2023, 1, 3, tzinfo=UTC))
    c4 = make_candle("150", datetime(2023, 1, 4, tzinfo=UTC))

    # Needs at least 3 historical candles (slow_period) + 1 current candle to evaluate crossover cleanly
    assert runner.process_candle(c1) is None
    assert runner.process_candle(c2) is None
    assert runner.process_candle(c3) is None

    # Now we have 3 historical candles, and c4 is the current candle.
    # History: [100, 100, 100]
    # Current: 150
    # Previous Fast MA: avg([100, 100]) = 100
    # Previous Slow MA: avg([100, 100, 100]) = 100
    # Current Fast MA: avg([100, 150]) = 125
    # Current Slow MA: avg([100, 100, 150]) = 116.66
    # Cross above!
    sig = runner.process_candle(c4)
    assert sig is not None
    assert sig.side == OrderSide.BUY

    # The strategy calculates internal state for crossover detection ("BULLISH")
    # but does NOT maintain actual position state.
    ctx = runner.contexts["BTC-USD_1h"]
    assert ctx.state["last_crossover"] == "BULLISH"
    assert "position" not in ctx.state


# -------------------------------------------------------------------------------------------------
# FIX 12: Look-ahead Protection
# -------------------------------------------------------------------------------------------------
def test_strategy_look_ahead_protection() -> None:
    runner = StrategyRunner("MA_Crossover_Reference", "1.0.0", {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")})

    c1 = make_candle("100", datetime(2023, 1, 1, tzinfo=UTC))
    c2 = make_candle("110", datetime(2023, 1, 2, tzinfo=UTC))
    c3 = make_candle("90", datetime(2023, 1, 3, tzinfo=UTC))

    runner.process_candle(c1)
    runner.process_candle(c2)

    ctx = runner.contexts["BTC-USD_1h"]
    # History after processing c2 contains c1 and c2. c3 is completely unknown.
    assert len(ctx.history) == 2
    assert c3 not in ctx.history
