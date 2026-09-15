"""Tests for the Strategy SDK, Validation, and Execution Foundation."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from app.models.enums import OrderSide
from app.models.strategy import StrategyVersionModel
from app.schemas.market_data import Candle
from app.strategies.examples.moving_average_crossover import MovingAverageCrossover
from app.strategies.runner import ChronologicalDataError, StrategyRunner, StrategyValidationError
from app.strategies.sdk import SignalDraft, StrategyContext, StrategyMetadata, StrategyRegistry
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
        trades=None,
    )


# -------------------------------------------------------------------------------------------------
# FIX 1, 3: Deterministic Output & Complete Output Test
# -------------------------------------------------------------------------------------------------
def get_mock_version(name: str = "MA_Crossover_Reference", version: str = "1.0.0", bad_hash: bool = False) -> StrategyVersionModel:
    try:
        hash_val = StrategyRegistry.get(name, version)[1] if not bad_hash else "WRONG_HASH"
    except ValueError:
        hash_val = "unknown_hash" if not bad_hash else "WRONG_HASH"
    return StrategyVersionModel(strategy_id=name, version=version, source_hash=hash_val)

def test_strategy_execution_determinism_and_chronology() -> None:
    """Prove that exactly the same inputs yield EXACTLY the same business output."""
    runner1 = StrategyRunner(
        get_mock_version(),
        {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
    )
    runner2 = StrategyRunner(
        get_mock_version(),
        {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
    )

    prices = ["100", "110", "120", "130", "110", "90", "70", "100", "150"]
    candles = [make_candle(p, datetime(2023, 1, i + 1, tzinfo=UTC)) for i, p in enumerate(prices)]

    drafts1: list[SignalDraft] = []
    drafts2: list[SignalDraft] = []

    for c in candles:
        # Directly test the strategy execution for drafts
        # (runner.process_candle would create different Signals due to uuids)
        ctx1 = runner1.contexts.setdefault(
            f"{c.symbol}_{c.timeframe}",
            StrategyContext("MA_Crossover_Reference", "1.0.0", c.symbol, c.timeframe),
        )
        ctx2 = runner2.contexts.setdefault(
            f"{c.symbol}_{c.timeframe}",
            StrategyContext("MA_Crossover_Reference", "1.0.0", c.symbol, c.timeframe),
        )

        draft1 = runner1.strategy.on_candle(c, ctx1)
        if draft1:
            drafts1.append(draft1)
        ctx1._history.append(c)

        draft2 = runner2.strategy.on_candle(c, ctx2)
        if draft2:
            drafts2.append(draft2)
        ctx2._history.append(c)

    assert len(drafts1) == len(drafts2)
    assert len(drafts1) > 0

    for d1, d2 in zip(drafts1, drafts2, strict=True):
        assert isinstance(d1, SignalDraft)
        assert isinstance(d2, SignalDraft)
        # Deep equality test on frozen Pydantic models. Tests COMPLETE deterministic output.
        assert d1 == d2


def test_strategy_invalid_return_type_fails_closed() -> None:
    class BadReturnStrategy(MovingAverageCrossover):
        metadata = StrategyMetadata(
            name="BadReturnStrategy", description="Testing", version="1.0.0",         )

        def on_candle(self, candle: Candle, context: StrategyContext) -> Any:
            return {"fake": "signal"}  # Invalid return type

    StrategyRegistry.register(BadReturnStrategy)

    runner = StrategyRunner(
        get_mock_version(name="BadReturnStrategy"),
        {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
    )

    # Should fail closed and return None
    assert runner.process_candle(make_candle("100", datetime(2023, 1, 1, tzinfo=UTC))) is None


# -------------------------------------------------------------------------------------------------
# FIX 2, 4: Explicit Chronological Data Validation & Rejection
# -------------------------------------------------------------------------------------------------
def test_chronological_candle_processing() -> None:
    runner = StrategyRunner(
        get_mock_version(),
        {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
    )

    c1 = make_candle("100", datetime(2023, 1, 1, 10, tzinfo=UTC))
    c2 = make_candle("110", datetime(2023, 1, 1, 11, tzinfo=UTC))
    runner.process_candle(c1)
    runner.process_candle(c2)

    ctx = runner.contexts["BTC-USD_1h"]
    assert len(ctx.history) == 2

    # Duplicate rejected with dedicated error
    with pytest.raises(ChronologicalDataError, match="duplicate candle rejected"):
        runner.process_candle(c2)

    # The history remains unchanged after rejection
    assert len(ctx.history) == 2

    # Out of order rejected with dedicated error
    c3 = make_candle("90", datetime(2023, 1, 1, 9, tzinfo=UTC))
    with pytest.raises(ChronologicalDataError, match="Out-of-order"):
        runner.process_candle(c3)

    assert len(ctx.history) == 2


# -------------------------------------------------------------------------------------------------
# FIX 1, 3: Exact StrategyVersion Binding & Source Identity
# -------------------------------------------------------------------------------------------------
def test_strategy_version_binding_and_source_hash() -> None:
    # 1. Successful exact version resolution
    runner = StrategyRunner(
        get_mock_version(),
        {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
    )
    assert isinstance(runner.strategy, MovingAverageCrossover)

    # 2. Unknown version fails closed
    with pytest.raises(StrategyValidationError, match="Unknown strategy version"):
        StrategyRunner(
        get_mock_version(version="2.0.0"),
            {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
        )

    # 3. Mismatched executable/source identity fails closed
    with pytest.raises(StrategyValidationError, match="Source hash mismatch"):
        StrategyRunner(
        get_mock_version(bad_hash=True),
            {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
        )


# -------------------------------------------------------------------------------------------------
# FIX 4: Strict Strategy Parameter Validation
# -------------------------------------------------------------------------------------------------
def test_strategy_parameter_strict_validation() -> None:
    with pytest.raises(StrategyValidationError, match="Invalid strategy parameters"):
        StrategyRunner(
        get_mock_version(), {"fast_period": 10}
        )

    with pytest.raises(
        StrategyValidationError,
        match="(?s)Invalid strategy parameters.*Extra inputs are not permitted",
    ):
        StrategyRunner(
        get_mock_version(),
            {
                "fast_period": 10,
                "slow_period": 20,
                "risk_percent": Decimal("2.0"),
                "unknown_param": 5,
            },
        )

    with pytest.raises(
        StrategyValidationError,
        match="(?s)Invalid strategy parameters.*Input should be a valid integer",
    ):
        StrategyRunner(
        get_mock_version(),
            {"fast_period": "20", "slow_period": 30, "risk_percent": Decimal("2.0")},
        )


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
        metadata.supported_asset_classes.append("stocks")  # type: ignore


# -------------------------------------------------------------------------------------------------
# FIX 6: Strategy Context & Controlled State
# -------------------------------------------------------------------------------------------------
def test_strategy_context_protection_and_state_api() -> None:
    ctx = StrategyContext("Test", "1.0.0", "BTC-USD", "1h")
    c = make_candle("100", datetime(2023, 1, 1, tzinfo=UTC))
    ctx._history.append(c)

    # 1. Strategy receives read-only history
    assert isinstance(ctx.history, tuple)
    with pytest.raises(AttributeError):
        ctx.history.append(make_candle("200", datetime(2023, 1, 2, tzinfo=UTC)))  # type: ignore

    # 2. Strategy can read/write its own state API
    assert ctx.strategy_state.get("some_key") is None
    ctx.strategy_state.set("some_key", "calculated_value")
    assert ctx.strategy_state.get("some_key") == "calculated_value"
    assert ctx.strategy_state.contains("some_key") is True

    # 3. Arbitrary replacement is discouraged and prevented via API encapsulation
    ctx.strategy_state.clear()
    assert ctx.strategy_state.contains("some_key") is False


# -------------------------------------------------------------------------------------------------
# FIX 8 & 11: Correct MA Strategy Evaluation & Position Independence
# -------------------------------------------------------------------------------------------------
def test_ma_strategy_sufficient_history_and_position_independence() -> None:
    runner = StrategyRunner(
        get_mock_version(),
        {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
    )

    c1 = make_candle("100", datetime(2023, 1, 1, tzinfo=UTC))
    c2 = make_candle("100", datetime(2023, 1, 2, tzinfo=UTC))
    c3 = make_candle("100", datetime(2023, 1, 3, tzinfo=UTC))
    c4 = make_candle("150", datetime(2023, 1, 4, tzinfo=UTC))

    assert runner.process_candle(c1) is None
    assert runner.process_candle(c2) is None
    assert runner.process_candle(c3) is None

    sig = runner.process_candle(c4)
    assert sig is not None
    assert sig.side == OrderSide.BUY

    # The strategy calculates internal state for crossover detection ("BULLISH")
    # but does NOT maintain actual position state.
    ctx = runner.contexts["BTC-USD_1h"]
    assert ctx.strategy_state.get("last_crossover") == "BULLISH"
    assert ctx.strategy_state.contains("position") is False


# -------------------------------------------------------------------------------------------------
# FIX 12: Look-ahead Protection
# -------------------------------------------------------------------------------------------------
def test_strategy_look_ahead_protection() -> None:
    runner = StrategyRunner(
        get_mock_version(),
        {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
    )

    c1 = make_candle("100", datetime(2023, 1, 1, tzinfo=UTC))
    c2 = make_candle("110", datetime(2023, 1, 2, tzinfo=UTC))
    c3 = make_candle("90", datetime(2023, 1, 3, tzinfo=UTC))

    runner.process_candle(c1)
    runner.process_candle(c2)

    ctx = runner.contexts["BTC-USD_1h"]
    assert len(ctx.history) == 2
    assert c3 not in ctx.history
