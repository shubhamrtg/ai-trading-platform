"""Strategy SDK Contract.

Provides the base abstractions for defining trading strategies.
Strategies must be deterministic, isolated from execution, and yield Signals.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, ClassVar, Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.enums import OrderSide, SignalType
from app.schemas.market_data import Candle
from app.schemas.signal import Signal


class StrategyMetadata(BaseModel):
    """Immutable metadata for a strategy."""

    name: str = Field(..., description="Unique strategy identifier name")
    description: str = Field(..., description="Human readable description")
    version: str = Field(..., description="Semver version string")
    supported_asset_classes: list[str] = Field(default_factory=list)
    supported_timeframes: list[str] = Field(default_factory=list)
    required_indicators: list[str] = Field(default_factory=list)


class StrategyContext:
    """Execution context injected into the strategy.

    Provides isolated access to historical data and state,
    preventing direct broker or database access.
    """

    def __init__(
        self,
        strategy_id: str,
        strategy_version: str,
        symbol: str,
        timeframe: str,
    ):
        self.strategy_id = strategy_id
        self.strategy_version = strategy_version
        self.symbol = symbol
        self.timeframe = timeframe
        self.history: list[Candle] = []
        self.state: dict[str, Any] = {}

    def create_signal(
        self,
        side: OrderSide,
        signal_type: SignalType,
        candle: Candle,
        proposed_entry_price: Decimal | None = None,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        confidence: float | None = None,
        rationale: str | None = None,
    ) -> Signal:
        """Create a signal bound to this context and current execution time."""
        return Signal(
            signal_id=uuid4(),
            correlation_id=uuid4(),
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            symbol=self.symbol,
            timestamp=candle.timestamp,
            timeframe=self.timeframe,
            side=side,
            signal_type=signal_type,
            proposed_entry_price=proposed_entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=confidence,
            rationale=rationale,
            metadata={"source": "StrategyRunner"},
        )


class StrategyParameters(BaseModel):
    """Base class for strategy parameters.
    Strategies should subclass this to define their schema using Pydantic.
    """

    pass


TParams = TypeVar("TParams", bound=StrategyParameters)


class Strategy(ABC, Generic[TParams]):
    """Base Strategy class.

    A strategy must:
    1. Define its metadata and parameter schema.
    2. Be deterministic.
    3. Return Signals, not Orders.
    """

    metadata: ClassVar[StrategyMetadata]
    parameters_schema: ClassVar[type[TParams]]

    def __init__(self, parameters: TParams):
        self.parameters = parameters

    @abstractmethod
    def on_candle(self, candle: Candle, context: StrategyContext) -> Signal | None:
        """Process exactly one candle chronologically and optionally emit a Signal.

        Must be deterministic and must not mutate global state.
        """
        pass
