"""Tests for Phase H: Order Intent boundary layer."""

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.execution.intent import (
    InvalidOrderIntentError,
    OrderIntentLineageError,
    RejectedRiskDecisionError,
    TradingModeMismatchError,
    UnsupportedOrderSemanticsError,
    build_order_intent,
)
from app.models.enums import OrderSide, OrderType, RiskDecisionStatus, SignalType
from app.schemas.order import OrderIntent
from app.schemas.risk import RiskDecision
from app.schemas.signal import Signal


@pytest.fixture
def base_signal() -> Signal:
    # A standard signal lacking order semantics directly
    return Signal(
        signal_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        strategy_id="strat-1",
        strategy_version="1.0.0",
        symbol="BTC/USD",
        timestamp=datetime.now(timezone.utc),
        timeframe="1h",
        side=OrderSide.BUY,
        signal_type=SignalType.ENTRY,
        quantity=Decimal("1.0"),
        proposed_entry_price=Decimal("50000.0"),
        stop_loss=Decimal("45000.0"),
        take_profit=Decimal("60000.0"),
        confidence=0.9,
        rationale="Test signal",
    )


@pytest.fixture
def semantic_signal(base_signal: Signal) -> Signal:
    # A signal dynamically patched with explicit semantics for successful testing
    # Note: Pydantic v2 allows dynamic attributes if not strictly frozen
    sig = base_signal.model_copy()
    object.__setattr__(sig, "order_type", OrderType.LIMIT)
    return sig


@pytest.fixture
def approved_decision(base_signal: Signal) -> RiskDecision:
    return RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=base_signal.correlation_id,
        signal_id=base_signal.signal_id,
        status=RiskDecisionStatus.APPROVED,
        risk_policy_version="1.0.0",
        rejection_codes=[],
        rejection_reasons=[],
        calculated_risk=Decimal("5000.0"),
        calculated_quantity=Decimal("0.5"),
        risk_limit_applied=None,
        timestamp=datetime.now(timezone.utc),
    )


def test_approved_decision_creates_intent(semantic_signal: Signal, approved_decision: RiskDecision) -> None:
    settings = get_settings()
    
    intent = build_order_intent(
        signal=semantic_signal,
        decision=approved_decision,
        account_id="acc-123",
        trading_mode=settings.trading_mode.value
    )

    assert isinstance(intent, OrderIntent)
    assert intent.originating_signal_id == semantic_signal.signal_id
    assert intent.correlation_id == semantic_signal.correlation_id
    assert intent.quantity == approved_decision.calculated_quantity
    assert intent.side == semantic_signal.side
    assert intent.risk_decision_id == approved_decision.decision_id
    assert intent.risk_policy_version == approved_decision.risk_policy_version
    assert intent.strategy_id == semantic_signal.strategy_id
    assert intent.trading_mode == settings.trading_mode.value
    assert intent.order_type == OrderType.LIMIT
    assert intent.limit_price == semantic_signal.proposed_entry_price


def test_rejected_decision_cannot_create_intent(semantic_signal: Signal, approved_decision: RiskDecision) -> None:
    rejected_decision = approved_decision.model_copy(
        update={"status": RiskDecisionStatus.REJECTED, "calculated_quantity": None}
    )

    with pytest.raises(RejectedRiskDecisionError):
        build_order_intent(
            signal=semantic_signal,
            decision=rejected_decision,
            account_id="acc-123",
            trading_mode=get_settings().trading_mode.value
        )


def test_quantity_authority(semantic_signal: Signal, approved_decision: RiskDecision) -> None:
    assert semantic_signal.quantity == Decimal("1.0")
    assert approved_decision.calculated_quantity == Decimal("0.5")
    
    intent = build_order_intent(
        signal=semantic_signal,
        decision=approved_decision,
        account_id="acc-123",
        trading_mode=get_settings().trading_mode.value
    )

    assert intent.quantity == Decimal("0.5")


def test_invalid_quantity_blocked(semantic_signal: Signal, approved_decision: RiskDecision) -> None:
    invalid_decision = approved_decision.model_copy(update={"calculated_quantity": Decimal("-1.0")})

    with pytest.raises(InvalidOrderIntentError):
        build_order_intent(
            signal=semantic_signal,
            decision=invalid_decision,
            account_id="acc-123",
            trading_mode=get_settings().trading_mode.value
        )


def test_determinism(semantic_signal: Signal, approved_decision: RiskDecision) -> None:
    mode = get_settings().trading_mode.value
    intent1 = build_order_intent(semantic_signal, approved_decision, "acc-1", mode)
    intent2 = build_order_intent(semantic_signal, approved_decision, "acc-1", mode)
    
    assert intent1.intent_id == intent2.intent_id
    
    payload = {"account_id": "acc-1", "risk_decision_id": str(approved_decision.decision_id)}
    canonical_string = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    expected_id = uuid.uuid5(uuid.NAMESPACE_OID, canonical_string)
    
    assert intent1.intent_id == expected_id
    assert intent1.idempotency_key == canonical_string


def test_different_approved_decisions_produce_different_identities(
    semantic_signal: Signal, approved_decision: RiskDecision
) -> None:
    mode = get_settings().trading_mode.value
    intent1 = build_order_intent(semantic_signal, approved_decision, "acc-1", mode)
    
    decision2 = approved_decision.model_copy(update={"decision_id": uuid.uuid4()})
    intent2 = build_order_intent(semantic_signal, decision2, "acc-1", mode)
    
    assert intent1.intent_id != intent2.intent_id


def test_different_accounts_produce_different_identities(
    semantic_signal: Signal, approved_decision: RiskDecision
) -> None:
    mode = get_settings().trading_mode.value
    intent1 = build_order_intent(semantic_signal, approved_decision, "acc-1", mode)
    intent2 = build_order_intent(semantic_signal, approved_decision, "acc-2", mode)
    
    assert intent1.intent_id != intent2.intent_id


def test_immutability(semantic_signal: Signal, approved_decision: RiskDecision) -> None:
    intent = build_order_intent(
        semantic_signal,
        approved_decision,
        "acc-1",
        get_settings().trading_mode.value
    )
    
    with pytest.raises(ValidationError):
        intent.quantity = Decimal("999.0")
        
    with pytest.raises(ValidationError):
        intent.order_type = OrderType.MARKET


def test_lineage_mismatch_signal_id(semantic_signal: Signal, approved_decision: RiskDecision) -> None:
    mismatched_decision = approved_decision.model_copy(update={"signal_id": uuid.uuid4()})
    
    with pytest.raises(OrderIntentLineageError, match="Mismatched signal_id"):
        build_order_intent(semantic_signal, mismatched_decision, "acc-1", get_settings().trading_mode.value)


def test_lineage_mismatch_correlation_id(semantic_signal: Signal, approved_decision: RiskDecision) -> None:
    mismatched_decision = approved_decision.model_copy(update={"correlation_id": uuid.uuid4()})
    
    with pytest.raises(OrderIntentLineageError, match="Mismatched correlation_id"):
        build_order_intent(semantic_signal, mismatched_decision, "acc-1", get_settings().trading_mode.value)


def test_trading_mode_mismatch(semantic_signal: Signal, approved_decision: RiskDecision) -> None:
    settings = get_settings()
    auth_mode = settings.trading_mode.value
    bad_mode = "LIVE" if auth_mode != "LIVE" else "PAPER"
    
    with pytest.raises(TradingModeMismatchError):
        build_order_intent(semantic_signal, approved_decision, "acc-1", trading_mode=bad_mode)


def test_missing_order_semantics_fails(base_signal: Signal, approved_decision: RiskDecision) -> None:
    # base_signal has no order_type
    with pytest.raises(UnsupportedOrderSemanticsError, match="Missing canonical order semantics"):
        build_order_intent(base_signal, approved_decision, "acc-1", get_settings().trading_mode.value)


def test_unsupported_order_semantics_fails(semantic_signal: Signal, approved_decision: RiskDecision) -> None:
    object.__setattr__(semantic_signal, "order_type", "TRAILING_STOP")
    
    with pytest.raises(UnsupportedOrderSemanticsError, match="Unsupported canonical order type"):
        build_order_intent(semantic_signal, approved_decision, "acc-1", get_settings().trading_mode.value)


def test_market_order_semantics_does_not_infer_price(semantic_signal: Signal, approved_decision: RiskDecision) -> None:
    object.__setattr__(semantic_signal, "order_type", OrderType.MARKET)
    
    intent = build_order_intent(semantic_signal, approved_decision, "acc-1", get_settings().trading_mode.value)
    assert intent.order_type == OrderType.MARKET
    assert intent.limit_price is None


def test_limit_order_requires_price(semantic_signal: Signal, approved_decision: RiskDecision) -> None:
    # Remove proposed entry price while requesting LIMIT
    sig = semantic_signal.model_copy(update={"proposed_entry_price": None})
    object.__setattr__(sig, "order_type", OrderType.LIMIT)
    
    with pytest.raises(UnsupportedOrderSemanticsError, match="requires a proposed_entry_price"):
        build_order_intent(sig, approved_decision, "acc-1", get_settings().trading_mode.value)


def test_stop_order_requires_explicit_stop_price(semantic_signal: Signal, approved_decision: RiskDecision) -> None:
    # Request STOP_MARKET without an explicit stop_price field on Signal
    object.__setattr__(semantic_signal, "order_type", OrderType.STOP_MARKET)
    
    with pytest.raises(UnsupportedOrderSemanticsError, match="requires an explicit stop_price field"):
        build_order_intent(semantic_signal, approved_decision, "acc-1", get_settings().trading_mode.value)

