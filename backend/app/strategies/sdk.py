"""Strategy SDK Contract.

Provides the base abstractions for defining trading strategies.
Strategies must be deterministic, isolated from execution, and yield Signals.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderSide, SignalType
from app.schemas.market_data import Candle


class SignalDraft(BaseModel):
    """Deterministic business output of a strategy.
    
    Contains NO runtime identity or orchestration fields.
    """
    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: str
    side: OrderSide
    signal_type: SignalType
    proposed_entry_price: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    rationale: str | None = None


class StrategyMetadata(BaseModel):
    """Immutable metadata for a strategy."""
    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Unique strategy identifier name")
    description: str = Field(..., description="Human readable description")
    version: str = Field(..., description="Semver version string")
    supported_asset_classes: tuple[str, ...] = Field(default_factory=tuple)
    supported_timeframes: tuple[str, ...] = Field(default_factory=tuple)
    required_indicators: tuple[str, ...] = Field(default_factory=tuple)


class StrategyContext:
    """Execution context injected into the strategy.

    Provides isolated read-only access to historical data and state,
    preventing direct broker or database access.
    """

    def __init__(self, strategy_id: str, strategy_version: str, symbol: str, timeframe: str):
        self._strategy_id = strategy_id
        self._strategy_version = strategy_version
        self._symbol = symbol
        self._timeframe = timeframe
        self._history: list[Candle] = []
        self.state: dict[str, Any] = {}

    @property
    def history(self) -> tuple[Candle, ...]:
        """Read-only access to the historical candles."""
        return tuple(self._history)


class StrategyParameters(BaseModel):
    """Base class for strategy parameters.
    Strategies should subclass this to define their schema using Pydantic.
    """
    model_config = ConfigDict(extra="forbid", strict=True)


TParams = TypeVar("TParams", bound=StrategyParameters)


class Strategy(ABC, Generic[TParams]):
    """Base Strategy class.

    A strategy must:
    1. Define its metadata and parameter schema.
    2. Be deterministic.
    3. Return SignalDrafts, not Orders or Signals with runtime IDs.
    """

    metadata: ClassVar[StrategyMetadata]
    parameters_schema: ClassVar[type[TParams]]

    def __init__(self, parameters: TParams):
        self.parameters = parameters

    @abstractmethod
    def on_candle(self, candle: Candle, context: StrategyContext) -> SignalDraft | None:
        """Process exactly one candle chronologically and optionally emit a SignalDraft.

        Must be deterministic and must not mutate global state.
        """
        pass


class StrategyRegistry:
    """Registry to bind exact StrategyVersion strings to executable implementations."""
    _strategies: dict[tuple[str, str], type[Strategy[Any]]] = {}

    @classmethod
    def register(cls, strategy_class: type[Strategy[Any]]) -> None:
        key = (strategy_class.metadata.name, strategy_class.metadata.version)
        if key in cls._strategies:
            raise ValueError(f"Strategy {key} already registered")
        cls._strategies[key] = strategy_class

    @classmethod
    def get(cls, name: str, version: str) -> type[Strategy[Any]]:
        key = (name, version)
        if key not in cls._strategies:
            raise ValueError(f"Unknown strategy version: {key}")
        return cls._strategies[key]

    @classmethod
    def clear(cls) -> None:
        cls._strategies.clear()
