"""Order Intent boundary layer.

Responsible for safely translating an approved RiskDecision into an OrderIntent.
"""

import json
import uuid

from app.config import get_settings
from app.models.enums import OrderType, RiskDecisionStatus
from app.schemas.order import OrderIntent
from app.schemas.risk import RiskDecision
from app.schemas.signal import Signal


class RejectedRiskDecisionError(ValueError):
    """Raised when trying to create an OrderIntent from a rejected RiskDecision."""


class UnsupportedOrderSemanticsError(ValueError):
    """Raised when the order semantics are not supported or explicitly defined."""


class InvalidOrderIntentError(ValueError):
    """Raised when the OrderIntent conversion fails structural validation."""


class OrderIntentLineageError(ValueError):
    """Raised when the Signal and RiskDecision lineage does not match."""


class TradingModeMismatchError(ValueError):
    """Raised when the requested trading mode conflicts with the authoritative mode."""


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
    # 1. Lineage Validation
    if decision.signal_id != signal.signal_id:
        raise OrderIntentLineageError("Mismatched signal_id between RiskDecision and Signal.")
    if decision.correlation_id != signal.correlation_id:
        raise OrderIntentLineageError("Mismatched correlation_id between RiskDecision and Signal.")
        
    if hasattr(decision, "strategy_id") and hasattr(signal, "strategy_id"):
        if getattr(decision, "strategy_id") != getattr(signal, "strategy_id"):
            raise OrderIntentLineageError("Mismatched strategy_id between RiskDecision and Signal.")
    if hasattr(decision, "strategy_version") and hasattr(signal, "strategy_version"):
        if getattr(decision, "strategy_version") != getattr(signal, "strategy_version"):
            raise OrderIntentLineageError("Mismatched strategy_version between RiskDecision and Signal.")

    # 2. Approval Gate
    if decision.status != RiskDecisionStatus.APPROVED:
        raise RejectedRiskDecisionError(f"Cannot create OrderIntent from {decision.status.value} decision.")
        
    # 3. Quantity Authority
    if decision.calculated_quantity is None or decision.calculated_quantity <= 0:
        raise InvalidOrderIntentError("Approved RiskDecision must have a positive calculated_quantity.")

    # 4. Trading Mode Authority
    settings = get_settings()
    auth_mode = settings.trading_mode.value
    if trading_mode != auth_mode:
        raise TradingModeMismatchError(
            f"Requested trading mode {trading_mode} conflicts with global authoritative mode {auth_mode}."
        )

    # 5. Order Semantics Validation
    # We must NOT invent order semantics.
    # The domain must provide a canonical order type.
    if not hasattr(signal, "order_type") or getattr(signal, "order_type") is None:
        raise UnsupportedOrderSemanticsError("Missing canonical order semantics (order_type) in Signal.")
        
    order_type = getattr(signal, "order_type")
    if not isinstance(order_type, OrderType):
        try:
            order_type = OrderType(order_type)
        except ValueError:
            raise UnsupportedOrderSemanticsError(f"Unsupported canonical order type: {order_type}") from None

    # Validate price requirements according to the explicitly provided order type
    limit_price = None
    stop_price = None
    if order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT):
        if signal.proposed_entry_price is None:
            raise UnsupportedOrderSemanticsError(f"{order_type.value} requires a proposed_entry_price.")
        limit_price = signal.proposed_entry_price

    if order_type in (OrderType.STOP_MARKET, OrderType.STOP_LIMIT):
        # We enforce that the domain explicitly defines a stop_price property for stop semantics
        # or we fail closed. The Signal has `proposed_entry_price` but we should not implicitly
        # assume it's the stop price without domain support.
        # However, to support STOP orders if they provide a stop_price attribute...
        if not hasattr(signal, "stop_price") or getattr(signal, "stop_price") is None:
             raise UnsupportedOrderSemanticsError(
                 f"{order_type.value} requires an explicit stop_price field, which is missing from Signal."
             )
        stop_price = getattr(signal, "stop_price")

    # 6. Deterministic Identity
    identity_payload = {
        "account_id": account_id,
        "risk_decision_id": str(decision.decision_id)
    }
    canonical_string = json.dumps(identity_payload, sort_keys=True, separators=(",", ":"))
    intent_id = uuid.uuid5(uuid.NAMESPACE_OID, canonical_string)

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
        idempotency_key=canonical_string,
        creation_timestamp=decision.timestamp,
        risk_policy_version=decision.risk_policy_version,
        strategy_id=signal.strategy_id,
        strategy_version=signal.strategy_version,
        trading_mode=auth_mode,
    )
