"""Strategy Execution Service.

Responsible for instantiating strategies, validating their parameters,
feeding them market data chronologically, and collecting signals.
"""

import logging
from typing import Any
from uuid import uuid4

from app.schemas.market_data import Candle
from app.schemas.signal import Signal
from app.strategies.sdk import SignalDraft, StrategyContext, StrategyRegistry

logger = logging.getLogger(__name__)


class StrategyExecutionError(Exception):
    """Raised when a strategy throws an unexpected exception during execution."""

    pass


class StrategyValidationError(Exception):
    """Raised when a strategy fails validation (metadata, parameters, safety)."""

    pass


class ChronologicalDataError(Exception):
    """Raised when market data arrives out of order or with duplicate timestamps."""

    pass


from app.models.strategy import StrategyVersionModel


class StrategyRunner:
    """Isolates and executes a strategy deterministically."""

    def __init__(
        self,
        version_record: StrategyVersionModel,
        parameters_dict: dict[str, Any],
    ):
        # 0. Version and Source Identity Binding
        try:
            self.strategy_class, actual_hash = StrategyRegistry.get(
                version_record.strategy_id, version_record.version
            )
        except Exception as e:
            raise StrategyValidationError(f"Could not resolve strategy version: {e}") from e

        if actual_hash != version_record.source_hash:
            raise StrategyValidationError(
                f"Source hash mismatch. Expected {version_record.source_hash}, "
                f"but got {actual_hash}."
            )

        # 1. Parameter Validation
        try:
            # Pydantic handles type coercion, required fields, constraints
            self.parameters = self.strategy_class.parameters_schema.model_validate(parameters_dict)
        except Exception as e:
            raise StrategyValidationError(f"Invalid strategy parameters: {e}") from e

        # 2. Instantiation (ensure it's instantiable)
        try:
            self.strategy = self.strategy_class(parameters=self.parameters)
        except Exception as e:
            raise StrategyValidationError(f"Failed to instantiate strategy: {e}") from e

        # Maintains one context per symbol_timeframe
        self.contexts: dict[str, StrategyContext] = {}

    def _get_or_create_context(self, symbol: str, timeframe: str) -> StrategyContext:
        key = f"{symbol}_{timeframe}"
        if key not in self.contexts:
            self.contexts[key] = StrategyContext(
                strategy_id=self.strategy_class.metadata.name,
                strategy_version=self.strategy_class.metadata.version,
                symbol=symbol,
                timeframe=timeframe,
            )
        return self.contexts[key]

    def process_candle(self, candle: Candle) -> Signal | None:
        """Chronologically process a single candle and return a Signal if emitted.

        Look-ahead protection is inherently provided: the strategy is only provided
        the current `candle`, and the context history is appended strictly sequentially.
        """
        context = self._get_or_create_context(candle.symbol, candle.timeframe)

        # Enforce chronological processing.
        # Explicitly reject invalid data without corrupting history.
        if context._history:
            if candle.timestamp <= context._history[-1].timestamp:
                raise ChronologicalDataError(
                    f"Out-of-order or duplicate candle rejected: "
                    f"{candle.timestamp} <= {context._history[-1].timestamp}"
                )

        try:
            draft = self.strategy.on_candle(candle, context)

            # Validate Strategy Return Type
            if draft is not None and not isinstance(draft, SignalDraft):
                raise StrategyValidationError(
                    f"Strategy returned invalid type: {type(draft)}. Must return SignalDraft or None."
                )

            # After successful processing of the candle, append it to canonical history.
            context._history.append(candle)

            if draft is None:
                return None

            # Create the final runtime Signal by appending non-deterministic orchestration fields
            return Signal(
                signal_id=uuid4(),
                correlation_id=uuid4(),
                strategy_id=self.strategy_class.metadata.name,
                strategy_version=self.strategy_class.metadata.version,
                symbol=draft.symbol,
                timestamp=candle.timestamp,
                timeframe=draft.timeframe,
                side=draft.side,
                signal_type=draft.signal_type,
                proposed_entry_price=draft.proposed_entry_price,
                stop_loss=draft.stop_loss,
                take_profit=draft.take_profit,
                confidence=draft.confidence,
                rationale=draft.rationale,
                metadata={"source": "StrategyRunner"},
            )

        except StrategyValidationError:
            raise
        except Exception as e:
            logger.error(
                f"Strategy {self.strategy_class.metadata.name} "
                f"failed on candle {candle.timestamp}: {e}"
            )
            raise StrategyExecutionError(
                f"Strategy {self.strategy_class.metadata.name} failed unexpectedly during execution."
            ) from e
