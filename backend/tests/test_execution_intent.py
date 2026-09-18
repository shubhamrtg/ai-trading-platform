"""Tests for Phase H: Order Intent boundary layer."""

from app.risk.capability import ApprovedRiskCapability

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.config.settings import TradingMode
from app.execution.intent import (
    InvalidOrderIntentError,
    OrderIntentLineageError,
    RejectedRiskDecisionError,
    UnsupportedOrderSemanticsError,
    build_order_intent,
)
from app.models.enums import OrderSide, OrderType, RiskDecisionStatus, SignalType
from app.risk.engine import RiskEngine
from app.schemas.order import OrderIntent
from app.schemas.risk import RiskContext, RiskDecision, RiskPolicy
from app.schemas.signal import Signal
from pydantic import ValidationError


@pytest.fixture
def valid_signal() -> Signal:
    # A standard valid signal natively equipped with explicit semantics
    return Signal(
        signal_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        strategy_id="strat-1",
        strategy_version="1.0.0",
        symbol="BTC/USD",
        timestamp=datetime.now(UTC),
        timeframe="1h",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        signal_type=SignalType.ENTRY,
        quantity=Decimal("1.0"),
        proposed_entry_price=Decimal("50000.0"),
        stop_loss=Decimal("45000.0"),
        take_profit=Decimal("60000.0"),
        confidence=0.9,
        rationale="Test signal",
    )


@pytest.fixture
def approved_decision(valid_signal: Signal) -> RiskDecision:
    engine = RiskEngine()
    context = RiskContext(
        account_id="acc-123",
        trading_mode=TradingMode.PAPER,
        current_position=Decimal("0.0"),
        current_exposure=Decimal("0.0"),
        portfolio_equity=Decimal("100000.0"),
        peak_equity=Decimal("100000.0"),
        current_equity=Decimal("100000.0"),
        available_cash=Decimal("100000.0"),
        daily_pnl=Decimal("0.0"),
        trading_halted=False,
        evaluated_at=datetime.now(UTC),
    )
    policy = RiskPolicy(
        version="1.0.0",
        max_order_quantity=Decimal("10.0"),
        max_position_quantity=Decimal("10.0"),
        max_exposure_amount=Decimal("100000.0"),
        max_exposure_percent=Decimal("1.0"),
        max_risk_per_trade=Decimal("10000.0"),
        max_daily_loss=Decimal("5000.0"),
        max_drawdown_percent=Decimal("0.2"),
        trading_halted=False,
    )
    decision = engine.evaluate(valid_signal, context, policy)
    assert decision.status == RiskDecisionStatus.APPROVED
    return decision


def test_adversarial_forged_decision_rejected(valid_signal: Signal) -> None:
    # Adversary creates an APPROVED decision manually without going through the RiskEngine
    forged_decision = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=valid_signal.correlation_id,
        signal_id=valid_signal.signal_id,
        status=RiskDecisionStatus.APPROVED,
        risk_policy_version="1.0.0",
        trading_mode=TradingMode.PAPER,
        rejection_codes=[],
        rejection_reasons=[],
        calculated_risk=Decimal("5000.0"),
        calculated_quantity=Decimal("0.5"),
        risk_limit_applied=None,
        timestamp=datetime.now(UTC),
    )

    with pytest.raises(ValueError, match="RiskDecision lacks a trusted ApprovedRiskCapability"):
        build_order_intent(
            signal=valid_signal,
            decision=forged_decision,
            account_id="acc-123",
        )


def test_approved_decision_creates_intent(
    valid_signal: Signal, approved_decision: RiskDecision
) -> None:
    intent = build_order_intent(
        signal=valid_signal,
        decision=approved_decision,
        account_id="acc-123",
    )

    assert isinstance(intent.intent, OrderIntent)
    assert intent.intent.originating_signal_id == valid_signal.signal_id
    assert intent.intent.correlation_id == valid_signal.correlation_id
    assert intent.intent.quantity == approved_decision.calculated_quantity
    assert intent.intent.side == valid_signal.side
    assert intent.intent.risk_decision_id == approved_decision.decision_id
    assert intent.intent.risk_policy_version == approved_decision.risk_policy_version
    assert intent.intent.strategy_id == valid_signal.strategy_id
    assert intent.intent.trading_mode == TradingMode.PAPER.value
    assert intent.intent.order_type == OrderType.LIMIT
    assert intent.intent.limit_price == valid_signal.proposed_entry_price


def test_rejected_decision_cannot_create_intent(
    valid_signal: Signal, approved_decision: RiskDecision
) -> None:
    rejected_decision = approved_decision.model_copy(
        update={"status": RiskDecisionStatus.REJECTED, "calculated_quantity": None}
    )

    with pytest.raises(RejectedRiskDecisionError):
        build_order_intent(
            signal=valid_signal,
            decision=rejected_decision,
            account_id="acc-123",
        )


def test_quantity_authority(valid_signal: Signal, approved_decision: RiskDecision) -> None:
    assert valid_signal.quantity == Decimal("1.0")

    # We forge a decision with a different calculated_quantity to prove the intent
    # respects the decision authority over the original signal quantity.
    decision = approved_decision.model_copy(
        update={"calculated_quantity": Decimal("0.5"), "decision_id": uuid.uuid4()}
    )
    decision._execution_capability = ApprovedRiskCapability._issue(
        decision_id=decision.decision_id,
        risk_policy_version=decision.risk_policy_version,
        trading_mode=decision.trading_mode,
        calculated_quantity=decision.calculated_quantity,  # type: ignore
        correlation_id=decision.correlation_id,
    )

    assert decision.calculated_quantity == Decimal("0.5")

    intent = build_order_intent(
        signal=valid_signal,
        decision=decision,
        account_id="acc-123",
    )

    assert intent.intent.quantity == Decimal("0.5")


def test_invalid_quantity_blocked(valid_signal: Signal, approved_decision: RiskDecision) -> None:
    invalid_decision = approved_decision.model_copy(update={"calculated_quantity": Decimal("-1.0")})

    with pytest.raises(InvalidOrderIntentError):
        build_order_intent(
            signal=valid_signal,
            decision=invalid_decision,
            account_id="acc-123",
        )


def test_determinism(valid_signal: Signal, approved_decision: RiskDecision) -> None:
    intent1 = build_order_intent(valid_signal, approved_decision, "acc-1")
    intent2 = build_order_intent(valid_signal, approved_decision, "acc-1")

    assert intent1.intent.intent_id == intent2.intent.intent_id

    payload = {"account_id": "acc-1", "risk_decision_id": str(approved_decision.decision_id)}
    canonical_string = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    expected_id = uuid.uuid5(uuid.NAMESPACE_OID, canonical_string)

    assert intent1.intent.intent_id == expected_id
    assert intent1.intent.idempotency_key == canonical_string


def test_different_approved_decisions_produce_different_identities(
    valid_signal: Signal, approved_decision: RiskDecision
) -> None:
    intent1 = build_order_intent(valid_signal, approved_decision, "acc-1")

    decision2 = approved_decision.model_copy(update={"decision_id": uuid.uuid4()})
    decision2._execution_capability = ApprovedRiskCapability._issue(
        decision_id=decision2.decision_id,
        risk_policy_version=decision2.risk_policy_version,
        trading_mode=decision2.trading_mode,
        calculated_quantity=decision2.calculated_quantity,  # type: ignore
        correlation_id=decision2.correlation_id,
    )
    intent2 = build_order_intent(valid_signal, decision2, "acc-1")

    assert intent1.intent.intent_id != intent2.intent.intent_id


def test_different_accounts_produce_different_identities(
    valid_signal: Signal, approved_decision: RiskDecision
) -> None:
    intent1 = build_order_intent(valid_signal, approved_decision, "acc-1")
    intent2 = build_order_intent(valid_signal, approved_decision, "acc-2")

    assert intent1.intent.intent_id != intent2.intent.intent_id


def test_immutability(valid_signal: Signal, approved_decision: RiskDecision) -> None:
    intent = build_order_intent(
        valid_signal,
        approved_decision,
        "acc-1",
    )

    with pytest.raises(ValidationError):
        intent.intent.quantity = Decimal("999.0")

    with pytest.raises(ValidationError):
        intent.intent.order_type = OrderType.MARKET


def test_lineage_mismatch_signal_id(valid_signal: Signal, approved_decision: RiskDecision) -> None:
    mismatched_decision = approved_decision.model_copy(update={"signal_id": uuid.uuid4()})

    with pytest.raises(OrderIntentLineageError, match="Mismatched signal_id"):
        build_order_intent(valid_signal, mismatched_decision, "acc-1")


def test_lineage_mismatch_correlation_id(
    valid_signal: Signal, approved_decision: RiskDecision
) -> None:
    mismatched_decision = approved_decision.model_copy(update={"correlation_id": uuid.uuid4()})

    with pytest.raises(OrderIntentLineageError, match="Mismatched correlation_id"):
        build_order_intent(valid_signal, mismatched_decision, "acc-1")


def test_market_order_semantics_does_not_infer_price(
    valid_signal: Signal, approved_decision: RiskDecision
) -> None:
    sig = valid_signal.model_copy(
        update={"order_type": OrderType.MARKET, "proposed_entry_price": None}
    )

    intent = build_order_intent(sig, approved_decision, "acc-1")
    assert intent.intent.order_type == OrderType.MARKET
    assert intent.intent.limit_price is None


def test_limit_order_requires_price(valid_signal: Signal, approved_decision: RiskDecision) -> None:
    # Remove proposed entry price while requesting LIMIT
    sig = valid_signal.model_copy(
        update={"order_type": OrderType.LIMIT, "proposed_entry_price": None}
    )

    with pytest.raises(UnsupportedOrderSemanticsError, match="requires a proposed_entry_price"):
        build_order_intent(sig, approved_decision, "acc-1")


def test_stop_market_order_requires_explicit_stop_price(
    valid_signal: Signal, approved_decision: RiskDecision
) -> None:
    # Request STOP_MARKET without an explicit stop_price field on Signal
    sig = valid_signal.model_copy(
        update={"order_type": OrderType.STOP_MARKET, "proposed_entry_price": None}
    )

    with pytest.raises(
        UnsupportedOrderSemanticsError,
        match="requires a proposed_entry_price to act as the stop trigger",
    ):
        build_order_intent(sig, approved_decision, "acc-1")


def test_stop_limit_order_fails_closed(
    valid_signal: Signal, approved_decision: RiskDecision
) -> None:
    sig = valid_signal.model_copy(update={"order_type": OrderType.STOP_LIMIT})
    with pytest.raises(
        UnsupportedOrderSemanticsError,
        match="STOP_LIMIT is not safely supported by the current Signal schema",
    ):
        build_order_intent(sig, approved_decision, "acc-1")
