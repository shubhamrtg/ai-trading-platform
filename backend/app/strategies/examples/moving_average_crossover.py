"""Reference Strategy Implementation: Moving Average Crossover.

This strategy is purposefully simple, intended to validate the architecture
rather than generate profit. It proves parameters, context history, and Signals.
"""

from decimal import Decimal

from app.models.enums import OrderSide, SignalType
from app.schemas.market_data import Candle
from app.schemas.signal import Signal
from app.strategies.sdk import Strategy, StrategyContext, StrategyMetadata, StrategyParameters
from pydantic import Field, model_validator


class MACrossoverParameters(StrategyParameters):
    """Strictly validated strategy parameters."""

    fast_period: int = Field(..., gt=0, description="Fast moving average period")
    slow_period: int = Field(..., gt=0, description="Slow moving average period")
    risk_percent: Decimal = Field(..., ge=0, le=5, description="Percentage of portfolio to risk")

    @model_validator(mode="after")
    def validate_periods(self) -> "MACrossoverParameters":
        if self.slow_period <= self.fast_period:
            raise ValueError("slow_period must be greater than fast_period")
        return self


class MovingAverageCrossover(Strategy[MACrossoverParameters]):
    metadata = StrategyMetadata(
        name="MA_Crossover_Reference",
        description="A simple Moving Average Crossover for architectural validation.",
        version="1.0.0",
        supported_asset_classes=["crypto", "stocks"],
        supported_timeframes=["1h", "1d"],
        required_indicators=[],
    )

    parameters_schema = MACrossoverParameters

    def on_candle(self, candle: Candle, context: StrategyContext) -> Signal | None:
        """Evaluate the strategy on a new candle."""

        # State management (initialize on first run)
        if "position" not in context.state:
            context.state["position"] = None  # None, "LONG", or "SHORT"

        # Validate we have enough history to compute the slow MA
        history_length = len(context.history) + 1  # include current candle
        if history_length < self.parameters.slow_period:
            return None

        # Simple Moving Average calculation
        # In a real system, we'd use vectorized pandas/numpy or TA-Lib instead of looping python lists,
        # but this is fine for architectural validation.
        closes = [c.close for c in context.history] + [candle.close]

        fast_closes = closes[-self.parameters.fast_period :]
        slow_closes = closes[-self.parameters.slow_period :]

        fast_ma = sum(fast_closes) / len(fast_closes)
        slow_ma = sum(slow_closes) / len(slow_closes)

        # Look at the previous MA to detect crossover
        prev_fast_closes = closes[-self.parameters.fast_period - 1 : -1]
        prev_slow_closes = closes[-self.parameters.slow_period - 1 : -1]

        prev_fast_ma = sum(prev_fast_closes) / len(prev_fast_closes)
        prev_slow_ma = sum(prev_slow_closes) / len(prev_slow_closes)

        # Crossover logic
        cross_above = prev_fast_ma <= prev_slow_ma and fast_ma > slow_ma
        cross_below = prev_fast_ma >= prev_slow_ma and fast_ma < slow_ma

        current_position = context.state["position"]

        if cross_above and current_position != "LONG":
            # Generate BUY Signal
            context.state["position"] = "LONG"
            return context.create_signal(
                side=OrderSide.BUY,
                signal_type=SignalType.ENTRY,
                candle=candle,
                confidence=0.8,
                rationale="Fast MA crossed above Slow MA",
            )

        if cross_below and current_position != "SHORT":
            # Generate SELL Signal (closing LONG, or entering SHORT)
            context.state["position"] = "SHORT"
            return context.create_signal(
                side=OrderSide.SELL,
                signal_type=SignalType.EXIT if current_position == "LONG" else SignalType.ENTRY,
                candle=candle,
                confidence=0.8,
                rationale="Fast MA crossed below Slow MA",
            )

        return None
