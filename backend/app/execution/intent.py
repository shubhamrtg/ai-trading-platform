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
    requested_trading_mode: str | None = None,
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

    # 2. Approval Gate
    if decision.status != RiskDecisionStatus.APPROVED:
        raise RejectedRiskDecisionError(f"Cannot create OrderIntent from {decision.status.value} decision.")

    # 3. Quantity Authority
    if decision.calculated_quantity is None or decision.calculated_quantity <= 0:
        raise InvalidOrderIntentError("Approved RiskDecision must have a positive calculated_quantity.")

    # 4. Trading Mode Authority
    settings = get_settings()
    auth_mode = settings.trading_mode.value
    if requested_trading_mode is not None and requested_trading_mode != auth_mode:
        raise TradingModeMismatchError(
            f"Requested trading mode {requested_trading_mode} conflicts with authoritative mode {auth_mode}."
        )

    # 5. Order Semantics Validation
    # Do NOT invent order semantics. Must be explicitly defined in domain (e.g., Signal metadata).
    order_type_raw = signal.metadata.get("order_type") if hasattr(signal, "metadata") else None
    if not order_type_raw:
        raise UnsupportedOrderSemanticsError("Order semantics not explicitly defined in Signal.")

    try:
        order_type = OrderType(order_type_raw)
    except ValueError:
        raise UnsupportedOrderSemanticsError(f"Unsupported explicit order type: {order_type_raw}")

    # Validate price requirements according to the explicitly provided order type
    limit_price = None
    stop_price = None
    if order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT):
        if signal.proposed_entry_price is None:
            raise UnsupportedOrderSemanticsError(f"{order_type.value} requires a proposed_entry_price.")
        limit_price = signal.proposed_entry_price

    if order_type in (OrderType.STOP_MARKET, OrderType.STOP_LIMIT):
        # The existing Signal schema does not have a top-level stop_price for entry.
        # It has proposed_entry_price, stop_loss, take_profit.
        # If STOP_MARKET is requested, we assume proposed_entry_price acts as the stop price.
        if signal.proposed_entry_price is None:
             raise UnsupportedOrderSemanticsError(f"{order_type.value} requires a proposed_entry_price.")
        stop_price = signal.proposed_entry_price
        if order_type == OrderType.STOP_LIMIT:
             # Just use it for both if not explicitly split, or require it in metadata.
             # Safest: look for explicit stop_price in metadata if STOP_LIMIT.
             explicit_stop = signal.metadata.get("stop_price")
             if explicit_stop is None:
                 raise UnsupportedOrderSemanticsError("STOP_LIMIT requires explicit stop_price in metadata.")
             stop_price = explicit_stop

    # 6. Deterministic Identity
    # Use canonical serialization to avoid delimiter ambiguity
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
