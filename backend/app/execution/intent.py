"""Order Intent boundary layer.

Responsible for safely translating an approved RiskDecision into an OrderIntent.
"""

import uuid
from typing import Any

from app.models.enums import OrderType, RiskDecisionStatus
from app.schemas.order import OrderIntent
from app.schemas.risk import RiskDecision
from app.schemas.signal import Signal


class RejectedRiskDecisionError(ValueError):
    """Raised when trying to create an OrderIntent from a rejected RiskDecision."""


class UnsupportedOrderSemanticsError(ValueError):
    """Raised when the order semantics are not supported by the execution engine."""


class InvalidOrderIntentError(ValueError):
    """Raised when the OrderIntent conversion fails validation."""


def build_order_intent(
    signal: Signal,
    decision: RiskDecision,
    account_id: str,
    trading_mode: str,
) -> OrderIntent:
    """Safely convert an approved RiskDecision into an OrderIntent.
    
    This is a pure, deterministic translation function that acts as the safety boundary
    between the Risk Engine and the Execution subsystem.
    """
    if decision.status != RiskDecisionStatus.APPROVED:
        raise RejectedRiskDecisionError(f"Cannot create OrderIntent from {decision.status.value} decision.")
        
    if decision.calculated_quantity is None or decision.calculated_quantity <= 0:
        raise InvalidOrderIntentError("Approved RiskDecision must have a positive calculated_quantity.")

    # Determine order type and prices based on signal semantics
    if signal.proposed_entry_price is not None:
        order_type = OrderType.LIMIT
        limit_price = signal.proposed_entry_price
        stop_price = None
    else:
        # Default to market order if no entry price was proposed
        order_type = OrderType.MARKET
        limit_price = None
        stop_price = None

    # Deterministic identity based on the exact decision and context variables
    idempotency_key = f"{decision.decision_id}-{account_id}"
    intent_id = uuid.uuid5(uuid.NAMESPACE_OID, idempotency_key)

    return OrderIntent(
        intent_id=intent_id,
        correlation_id=decision.correlation_id,
        originating_signal_id=signal.signal_id,
        risk_decision_id=decision.decision_id,
        account_id=account_id,
        symbol=signal.symbol,
        side=signal.side,
        order_type=order_type,
        quantity=decision.calculated_quantity,
        limit_price=limit_price,
        stop_price=stop_price,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        idempotency_key=idempotency_key,
        creation_timestamp=decision.timestamp,
        risk_policy_version=decision.risk_policy_version,
        strategy_id=signal.strategy_id,
        strategy_version=signal.strategy_version,
        trading_mode=trading_mode,
    )
