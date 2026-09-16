"""Reference Strategy Implementation: Moving Average Crossover.

This strategy is purposefully simple, intended to validate the architecture
rather than generate profit. It proves parameters, context history, and SignalDrafts.
"""

from decimal import Decimal

from app.models.enums import OrderSide, SignalType
from app.schemas.market_data import Candle
from app.strategies.sdk import (
    SignalDraft,
    Strategy,
    StrategyContext,
    StrategyMetadata,
    StrategyParameters,
    StrategyRegistry,
)
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
        supported_asset_classes=("crypto", "stocks"),
        supported_timeframes=("1h", "1d"),
        required_indicators=(),
    )

    parameters_schema = MACrossoverParameters

    def on_candle(self, candle: Candle, context: StrategyContext) -> SignalDraft | None:
        """Evaluate the strategy on a new candle."""

        # Validate we have enough history to compute the previous slow MA
        # A full previous window requires self.parameters.slow_period candles strictly in history
        if len(context.history) < self.parameters.slow_period:
            return None

        # Simple Moving Average calculation
        closes = [c.close for c in context.history] + [candle.close]

        # Current MAs (using candle.close and previous history)
        fast_closes = closes[-self.parameters.fast_period :]
        slow_closes = closes[-self.parameters.slow_period :]

        fast_ma = sum(fast_closes) / len(fast_closes)
        slow_ma = sum(slow_closes) / len(slow_closes)

        # Previous MAs (using ONLY history, completely ignoring current candle)
        prev_fast_closes = closes[-self.parameters.fast_period - 1 : -1]
        prev_slow_closes = closes[-self.parameters.slow_period - 1 : -1]

        prev_fast_ma = sum(prev_fast_closes) / len(prev_fast_closes)
        prev_slow_ma = sum(prev_slow_closes) / len(prev_slow_closes)

        # Crossover logic
        cross_above = prev_fast_ma <= prev_slow_ma and fast_ma > slow_ma
        cross_below = prev_fast_ma >= prev_slow_ma and fast_ma < slow_ma

        last_crossover = context.strategy_state.get("last_crossover")

        if cross_above and last_crossover != "BULLISH":
            # Generate BUY SignalDraft
            context.strategy_state.set("last_crossover", "BULLISH")
            return SignalDraft(
                symbol=candle.symbol,
                timeframe=candle.timeframe,
                side=OrderSide.BUY,
                signal_type=SignalType.ENTRY,
                confidence=0.8,
                rationale="Fast MA crossed above Slow MA",
            )

        if cross_below and last_crossover != "BEARISH":
            # Generate SELL SignalDraft
            context.strategy_state.set("last_crossover", "BEARISH")
            return SignalDraft(
                symbol=candle.symbol,
                timeframe=candle.timeframe,
                side=OrderSide.SELL,
                signal_type=SignalType.ENTRY,  # Simplified: just an entry
                confidence=0.8,
                rationale="Fast MA crossed below Slow MA",
            )

        return None


StrategyRegistry.register(MovingAverageCrossover)
