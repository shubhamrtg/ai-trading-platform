"""Tests for the deterministic Risk Engine (Phase G)."""

from datetime import datetime, UTC
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.enums import OrderSide, RiskDecisionStatus, RiskRejectionCode, SignalType
from app.risk.engine import RiskEngine
from app.schemas.risk import RiskContext, RiskDecision, RiskPolicy
from app.schemas.signal import Signal


@pytest.fixture
def base_policy() -> RiskPolicy:
    return RiskPolicy(
        version="1.0.0",
        max_order_quantity=Decimal("10.0"),
        max_position_quantity=Decimal("50.0"),
        max_exposure_amount=Decimal("10000.0"),
        max_exposure_percent=Decimal("0.5"),
        max_risk_per_trade=Decimal("500.0"),
        max_daily_loss=Decimal("2000.0"),
        max_drawdown_percent=Decimal("0.1"),
        trading_halted=False,
    )


@pytest.fixture
def base_context() -> RiskContext:
    return RiskContext(
        portfolio_equity=Decimal("20000.0"),
        available_cash=Decimal("20000.0"),
        current_position=Decimal("10.0"),
        current_exposure=Decimal("1000.0"),
        daily_pnl=Decimal("0.0"),
        peak_equity=Decimal("20000.0"),
        current_equity=Decimal("20000.0"),
        trading_halted=False,
        evaluated_at=datetime.now(UTC),
    )


@pytest.fixture
def base_signal() -> Signal:
    return Signal(
        signal_id=uuid4(),
        correlation_id=uuid4(),
        strategy_id="test_strategy",
        strategy_version="1.0.0",
        symbol="BTC-USD",
        timeframe="1h",
        timestamp=datetime.now(UTC),
        side=OrderSide.BUY,
        signal_type=SignalType.ENTRY,
        quantity=Decimal("1.0"),
        proposed_entry_price=Decimal("100.0"),
        stop_loss=Decimal("90.0"),
        take_profit=Decimal("120.0"),
        confidence=0.9,
        rationale=None,
    )


def test_determinism(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    
    dec1 = engine.evaluate(base_signal, base_context, base_policy)
    dec2 = engine.evaluate(base_signal, base_context, base_policy)
    
    assert dec1.decision_id == dec2.decision_id
    assert dec1.timestamp == dec2.timestamp == base_context.evaluated_at
    assert dec1.risk_policy_version == base_policy.version
    assert dec1.status == dec2.status
    assert dec1.rejection_codes == dec2.rejection_codes


def test_valid_signal_approved(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    decision = engine.evaluate(base_signal, base_context, base_policy)
    assert decision.status == RiskDecisionStatus.APPROVED
    assert decision.calculated_quantity == Decimal("1.0")
    assert decision.calculated_risk == Decimal("10.0")
    assert decision.risk_policy_version == "1.0.0"


def test_zero_or_negative_quantity_rejected(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    bad_signal = Signal.model_construct(**{**base_signal.model_dump(), "quantity": Decimal("0.0")})
    decision = engine.evaluate(bad_signal, base_context, base_policy)
    assert decision.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.INVALID_SIGNAL in decision.rejection_codes


def test_missing_stop_when_required(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    base_signal_no_stop = base_signal.model_copy(update={"stop_loss": None})
    decision = engine.evaluate(base_signal_no_stop, base_context, base_policy)
    assert decision.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.INSUFFICIENT_INFORMATION in decision.rejection_codes


def test_max_order_quantity(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    # Below limit
    base_signal_below = base_signal.model_copy(update={"quantity": Decimal("9.9")})
    assert engine.evaluate(base_signal_below, base_context, base_policy).status == RiskDecisionStatus.APPROVED

    # Exactly at limit
    base_signal_at = base_signal.model_copy(update={"quantity": Decimal("10.0")})
    assert engine.evaluate(base_signal_at, base_context, base_policy).status == RiskDecisionStatus.APPROVED

    # Above limit
    base_signal_above = base_signal.model_copy(update={"quantity": Decimal("10.1")})
    decision = engine.evaluate(base_signal_above, base_context, base_policy)
    assert decision.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.MAX_ORDER_QUANTITY_EXCEEDED in decision.rejection_codes


def test_max_position(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    # Context has 10 current position. Max is 50.
    policy = base_policy.model_copy(update={"max_order_quantity": Decimal("100.0")})
    
    # Below limit (10 + 39 = 49)
    base_signal_below = base_signal.model_copy(update={"quantity": Decimal("39.0")})
    assert engine.evaluate(base_signal_below, base_context, policy).status == RiskDecisionStatus.APPROVED

    # Exactly at limit (10 + 40 = 50)
    base_signal_at = base_signal.model_copy(update={"quantity": Decimal("40.0")})
    assert engine.evaluate(base_signal_at, base_context, policy).status == RiskDecisionStatus.APPROVED

    # Above limit (10 + 41 = 51)
    base_signal_above = base_signal.model_copy(update={"quantity": Decimal("41.0")})
    decision = engine.evaluate(base_signal_above, base_context, policy)
    assert decision.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.MAX_POSITION_EXCEEDED in decision.rejection_codes

    # Invalid sell beyond held position (long-only semantics)
    sell_signal = base_signal.model_copy(update={"side": OrderSide.SELL, "quantity": Decimal("11.0")})
    decision_sell = engine.evaluate(sell_signal, base_context, policy)
    assert decision_sell.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.UNSUPPORTED_ORDER_SEMANTICS in decision_sell.rejection_codes


def test_exposure_buy(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    policy = base_policy.model_copy(update={"max_order_quantity": Decimal("1000.0"), "max_position_quantity": Decimal("1000.0"), "max_risk_per_trade": Decimal("0.0")})
    
    # Current exposure = 1000
    # Max exposure = 10000
    # Equity = 20000, 50% = 10000
    
    # BUY 90 @ 100 -> 9000. Total = 10000. (Exactly at limit)
    sig_at = base_signal.model_copy(update={"quantity": Decimal("90.0")})
    assert engine.evaluate(sig_at, base_context, policy).status == RiskDecisionStatus.APPROVED

    # BUY 91 @ 100 -> 9100. Total = 10100 > 10000. (Exceeds limit)
    sig_above = base_signal.model_copy(update={"quantity": Decimal("91.0")})
    decision = engine.evaluate(sig_above, base_context, policy)
    assert decision.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.MAX_EXPOSURE_EXCEEDED in decision.rejection_codes


def test_exposure_sell_reducing(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    policy = base_policy.model_copy(update={"max_order_quantity": Decimal("1000.0"), "max_position_quantity": Decimal("1000.0"), "max_risk_per_trade": Decimal("0.0")})
    
    # Sell should reduce exposure and not be blocked by exposure limit
    # Suppose current exposure is 15000 (already above limit 10000)
    ctx_over = base_context.model_copy(update={"current_exposure": Decimal("15000.0"), "current_position": Decimal("150.0")})
    
    # A BUY would fail because it increases exposure over 10000
    sig_buy = base_signal.model_copy(update={"quantity": Decimal("1.0")})
    dec_buy = engine.evaluate(sig_buy, ctx_over, policy)
    assert dec_buy.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.MAX_EXPOSURE_EXCEEDED in dec_buy.rejection_codes
    
    # A SELL reduces exposure, should pass (SELL 50 @ 100 -> 5000)
    sig_sell = base_signal.model_copy(update={"side": OrderSide.SELL, "quantity": Decimal("50.0")})
    dec_sell = engine.evaluate(sig_sell, ctx_over, policy)
    assert dec_sell.status == RiskDecisionStatus.APPROVED


def test_exposure_missing_price(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    policy = base_policy.model_copy(update={"max_risk_per_trade": Decimal("0.0")})
    
    sig_no_price = base_signal.model_copy(update={"proposed_entry_price": None})
    decision_np = engine.evaluate(sig_no_price, base_context, policy)
    assert decision_np.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.INSUFFICIENT_INFORMATION in decision_np.rejection_codes


def test_trade_risk(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    
    # Below maximum: price=100, stop=50 -> risk=50 * 9 = 450 <= 500
    sig_below = base_signal.model_copy(update={"quantity": Decimal("9.0"), "stop_loss": Decimal("50.0")})
    assert engine.evaluate(sig_below, base_context, base_policy).status == RiskDecisionStatus.APPROVED

    # Exactly maximum: risk=50 * 10 = 500
    sig_at = base_signal.model_copy(update={"quantity": Decimal("10.0"), "stop_loss": Decimal("50.0")})
    assert engine.evaluate(sig_at, base_context, base_policy).status == RiskDecisionStatus.APPROVED

    # Above maximum: risk=50 * 11 = 550
    policy = base_policy.model_copy(update={"max_order_quantity": Decimal("100.0")})
    sig_above = base_signal.model_copy(update={"quantity": Decimal("11.0"), "stop_loss": Decimal("50.0")})
    decision = engine.evaluate(sig_above, base_context, policy)
    assert decision.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.MAX_RISK_PER_TRADE_EXCEEDED in decision.rejection_codes


def test_daily_loss(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    
    # Safe daily P&L (-1999)
    ctx_safe = base_context.model_copy(update={"daily_pnl": Decimal("-1999.0")})
    assert engine.evaluate(base_signal, ctx_safe, base_policy).status == RiskDecisionStatus.APPROVED

    # Exactly at boundary (-2000 >= 2000 max_daily_loss, should reject)
    ctx_at = base_context.model_copy(update={"daily_pnl": Decimal("-2000.0")})
    dec_at = engine.evaluate(base_signal, ctx_at, base_policy)
    assert dec_at.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.DAILY_LOSS_LIMIT_BREACHED in dec_at.rejection_codes

    # Beyond limit (-3000)
    ctx_beyond = base_context.model_copy(update={"daily_pnl": Decimal("-3000.0")})
    dec_beyond = engine.evaluate(base_signal, ctx_beyond, base_policy)
    assert dec_beyond.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.DAILY_LOSS_LIMIT_BREACHED in dec_beyond.rejection_codes


def test_drawdown(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    
    # Safe drawdown: peak=20k, current=19k -> 5% (limit 10%)
    ctx_safe = base_context.model_copy(update={"current_equity": Decimal("19000.0")})
    assert engine.evaluate(base_signal, ctx_safe, base_policy).status == RiskDecisionStatus.APPROVED

    # Exactly at boundary: current=18k -> 10%. Semantics says drawdown >= limit -> REJECT.
    ctx_at = base_context.model_copy(update={"current_equity": Decimal("18000.0")})
    dec_at = engine.evaluate(base_signal, ctx_at, base_policy)
    assert dec_at.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.MAX_DRAWDOWN_EXCEEDED in dec_at.rejection_codes

    # Beyond limit: current=17k -> 15%
    ctx_beyond = base_context.model_copy(update={"current_equity": Decimal("17000.0")})
    dec_beyond = engine.evaluate(base_signal, ctx_beyond, base_policy)
    assert dec_beyond.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.MAX_DRAWDOWN_EXCEEDED in dec_beyond.rejection_codes


def test_kill_switch_deduplication(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    
    # Via Context
    ctx_halted = base_context.model_copy(update={"trading_halted": True})
    dec_ctx = engine.evaluate(base_signal, ctx_halted, base_policy)
    assert dec_ctx.status == RiskDecisionStatus.REJECTED
    assert dec_ctx.rejection_codes.count(RiskRejectionCode.TRADING_HALTED) == 1

    # Via Policy
    pol_halted = base_policy.model_copy(update={"trading_halted": True})
    dec_pol = engine.evaluate(base_signal, base_context, pol_halted)
    assert dec_pol.status == RiskDecisionStatus.REJECTED
    assert dec_pol.rejection_codes.count(RiskRejectionCode.TRADING_HALTED) == 1

    # Via Both
    dec_both = engine.evaluate(base_signal, ctx_halted, pol_halted)
    assert dec_both.status == RiskDecisionStatus.REJECTED
    # Ensure it's not duplicated
    assert dec_both.rejection_codes.count(RiskRejectionCode.TRADING_HALTED) == 1


def test_multiple_violations(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    
    # Trigger quantity limit, exposure limit, and drawdown limit
    sig = base_signal.model_copy(update={"quantity": Decimal("1000000.0")})
    ctx = base_context.model_copy(update={"current_equity": Decimal("1000.0")})
    
    decision = engine.evaluate(sig, ctx, base_policy)
    assert decision.status == RiskDecisionStatus.REJECTED
    
    assert RiskRejectionCode.MAX_ORDER_QUANTITY_EXCEEDED in decision.rejection_codes
    assert RiskRejectionCode.MAX_POSITION_EXCEEDED in decision.rejection_codes
    assert RiskRejectionCode.MAX_EXPOSURE_EXCEEDED in decision.rejection_codes
    assert RiskRejectionCode.MAX_DRAWDOWN_EXCEEDED in decision.rejection_codes
    assert RiskRejectionCode.MAX_RISK_PER_TRADE_EXCEEDED in decision.rejection_codes


def test_immutability(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    
    sig_before = base_signal.model_copy()
    ctx_before = base_context.model_copy()
    pol_before = base_policy.model_copy()
    
    engine.evaluate(base_signal, base_context, base_policy)
    
    assert base_signal == sig_before
    assert base_context == ctx_before
    assert base_policy == pol_before


def test_architectural_no_execution_dependency() -> None:
    # Prove engine has no execution dependencies
    import inspect
    import app.risk.engine
    
    source = inspect.getsource(app.risk.engine)
    assert "broker" not in source.lower()
    assert "execute" not in source.lower() # no execution
    assert " import ai" not in source.lower()


def test_determinism_exposure_changes_identity(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    ctx1 = base_context.model_copy(update={"current_exposure": Decimal("10000.0")})
    ctx2 = base_context.model_copy(update={"current_exposure": Decimal("20000.0")})
    
    dec1 = engine.evaluate(base_signal, ctx1, base_policy)
    dec2 = engine.evaluate(base_signal, ctx2, base_policy)
    
    assert dec1.decision_id != dec2.decision_id

def test_determinism_portfolio_equity_changes_identity(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    ctx1 = base_context.model_copy(update={"portfolio_equity": Decimal("100000.0")})
    ctx2 = base_context.model_copy(update={"portfolio_equity": Decimal("200000.0")})
    
    dec1 = engine.evaluate(base_signal, ctx1, base_policy)
    dec2 = engine.evaluate(base_signal, ctx2, base_policy)
    
    assert dec1.decision_id != dec2.decision_id

def test_determinism_daily_pnl_changes_identity(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    ctx1 = base_context.model_copy(update={"daily_pnl": Decimal("100.0")})
    ctx2 = base_context.model_copy(update={"daily_pnl": Decimal("-100.0")})
    
    dec1 = engine.evaluate(base_signal, ctx1, base_policy)
    dec2 = engine.evaluate(base_signal, ctx2, base_policy)
    
    assert dec1.decision_id != dec2.decision_id

def test_determinism_position_changes_identity(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    ctx1 = base_context.model_copy(update={"current_position": Decimal("10.0")})
    ctx2 = base_context.model_copy(update={"current_position": Decimal("20.0")})
    
    dec1 = engine.evaluate(base_signal, ctx1, base_policy)
    dec2 = engine.evaluate(base_signal, ctx2, base_policy)
    
    assert dec1.decision_id != dec2.decision_id

def test_determinism_policy_configuration_changes_identity(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    # Keep version same, change exposure amount
    pol1 = base_policy.model_copy(update={"max_exposure_amount": Decimal("10000.0")})
    pol2 = base_policy.model_copy(update={"max_exposure_amount": Decimal("20000.0")})
    
    dec1 = engine.evaluate(base_signal, base_context, pol1)
    dec2 = engine.evaluate(base_signal, base_context, pol2)
    
    assert dec1.decision_id != dec2.decision_id

def test_determinism_timestamp_changes_identity(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    from datetime import timedelta
    engine = RiskEngine()
    ctx1 = base_context.model_copy(update={"evaluated_at": base_context.evaluated_at})
    ctx2 = base_context.model_copy(update={"evaluated_at": base_context.evaluated_at + timedelta(seconds=1)})
    
    dec1 = engine.evaluate(base_signal, ctx1, base_policy)
    dec2 = engine.evaluate(base_signal, ctx2, base_policy)
    
    assert dec1.decision_id != dec2.decision_id

def test_determinism_none_versus_zero(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    
    sig1 = base_signal.model_copy(update={"proposed_entry_price": None})
    sig2 = base_signal.model_copy(update={"proposed_entry_price": Decimal("0.0")})
    
    dec1 = engine.evaluate(sig1, base_context, base_policy)
    dec2 = engine.evaluate(sig2, base_context, base_policy)
    
    assert dec1.decision_id != dec2.decision_id

def test_determinism_string_delimiter_safety(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    
    # We can inject delimiter characters into string fields like strategy_id or version
    # Since we are using JSON with strict schemas now, `strategy_id="A|B", strategy_version="C"`
    # should be fundamentally distinct from `strategy_id="A", strategy_version="B|C"`
    sig1 = base_signal.model_copy(update={"strategy_id": "A|B", "strategy_version": "C"})
    sig2 = base_signal.model_copy(update={"strategy_id": "A", "strategy_version": "B|C"})
    
    dec1 = engine.evaluate(sig1, base_context, base_policy)
    dec2 = engine.evaluate(sig2, base_context, base_policy)
    
    assert dec1.decision_id != dec2.decision_id

def test_determinism_decimal_representation_safety(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    
    ctx1 = base_context.model_copy(update={"current_exposure": Decimal("100.00")})
    ctx2 = base_context.model_copy(update={"current_exposure": Decimal("100.01")})
    
    dec1 = engine.evaluate(base_signal, ctx1, base_policy)
    dec2 = engine.evaluate(base_signal, ctx2, base_policy)
    
    assert dec1.decision_id != dec2.decision_id

