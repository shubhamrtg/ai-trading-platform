"""Order Intent boundary layer.

Responsible for safely translating an approved RiskDecision into an OrderIntent.
"""

import json
import uuid

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


def build_order_intent(
    signal: Signal,
    decision: RiskDecision,
    account_id: str,
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
        if decision.strategy_id != signal.strategy_id:
            raise OrderIntentLineageError("Mismatched strategy_id between RiskDecision and Signal.")
    if hasattr(decision, "strategy_version") and hasattr(signal, "strategy_version"):
        if decision.strategy_version != signal.strategy_version:
            raise OrderIntentLineageError("Mismatched strategy_version between RiskDecision and Signal.")

    # 2. Approval Gate
    if decision.status != RiskDecisionStatus.APPROVED:
        raise RejectedRiskDecisionError(f"Cannot create OrderIntent from {decision.status.value} decision.")

    # 3. Quantity Authority
    if decision.calculated_quantity is None or decision.calculated_quantity <= 0:
        raise InvalidOrderIntentError("Approved RiskDecision must have a positive calculated_quantity.")

    # 4. Trading Mode Authority
    # Authoritative trading mode is exactly the mode under which RiskDecision was approved
    auth_mode = decision.trading_mode.value

    # 5. Order Semantics Validation
    # The domain must provide a canonical order type explicitly on the Signal.
    order_type = signal.order_type

    # Validate price requirements according to the explicitly provided order type
    limit_price = None
    stop_price = None
    if order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT):
        if signal.proposed_entry_price is None:
            raise UnsupportedOrderSemanticsError(f"{order_type.value} requires a proposed_entry_price.")
        limit_price = signal.proposed_entry_price

    if order_type in (OrderType.STOP_MARKET, OrderType.STOP_LIMIT):
        # We enforce that the domain explicitly defines a stop trigger price semantics.
        # Since the frozen domain documentation states `proposed_entry_price` is the "Proposed limit/stop price",
        # we map it to stop_price when STOP_MARKET is requested.
        # However, for STOP_LIMIT, we would need TWO prices (stop trigger + limit).
        # Since the domain only provides `proposed_entry_price`, we FAIL CLOSED on STOP_LIMIT.
        if order_type == OrderType.STOP_LIMIT:
            raise UnsupportedOrderSemanticsError(
                "STOP_LIMIT is not safely supported by the current Signal schema as it lacks independent limit and stop prices."
            )

        if signal.proposed_entry_price is None:
            raise UnsupportedOrderSemanticsError(f"{order_type.value} requires a proposed_entry_price to act as the stop trigger.")
        stop_price = signal.proposed_entry_price

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
