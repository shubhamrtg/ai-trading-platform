"""Tests for the deterministic Risk Engine (Phase G)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from app.models.enums import OrderSide, RiskDecisionStatus, RiskRejectionCode, SignalType
from app.risk.engine import RiskEngine
from app.schemas.risk import RiskContext, RiskPolicy
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


def test_valid_signal_approved(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    decision = engine.evaluate(base_signal, base_context, base_policy)
    assert decision.status == RiskDecisionStatus.APPROVED
    assert decision.calculated_quantity == Decimal("1.0")
    assert decision.calculated_risk == Decimal("10.0")


def test_zero_or_negative_quantity_rejected(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()
    # Construct bypassing pydantic validation if possible, or just mock it.
    # We can use model_construct.
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
    assert (
        engine.evaluate(base_signal_below, base_context, base_policy).status
        == RiskDecisionStatus.APPROVED
    )

    # Exactly at limit
    base_signal_at = base_signal.model_copy(update={"quantity": Decimal("10.0")})
    assert (
        engine.evaluate(base_signal_at, base_context, base_policy).status
        == RiskDecisionStatus.APPROVED
    )

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
    assert (
        engine.evaluate(base_signal_below, base_context, policy).status
        == RiskDecisionStatus.APPROVED
    )

    # Exactly at limit (10 + 40 = 50)
    base_signal_at = base_signal.model_copy(update={"quantity": Decimal("40.0")})
    assert (
        engine.evaluate(base_signal_at, base_context, policy).status == RiskDecisionStatus.APPROVED
    )

    # Above limit (10 + 41 = 51)
    base_signal_above = base_signal.model_copy(update={"quantity": Decimal("41.0")})
    decision = engine.evaluate(base_signal_above, base_context, policy)
    assert decision.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.MAX_POSITION_EXCEEDED in decision.rejection_codes

    # Invalid sell beyond held position (long-only semantics)
    sell_signal = base_signal.model_copy(
        update={"side": OrderSide.SELL, "quantity": Decimal("11.0")}
    )
    decision_sell = engine.evaluate(sell_signal, base_context, policy)
    assert decision_sell.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.UNSUPPORTED_ORDER_SEMANTICS in decision_sell.rejection_codes


def test_exposure(base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy) -> None:
    engine = RiskEngine()
    policy = base_policy.model_copy(
        update={
            "max_order_quantity": Decimal("1000.0"),
            "max_position_quantity": Decimal("1000.0"),
            "max_risk_per_trade": Decimal("100000.0"),
        }
    )

    # Below limit (qty=90, price=100 -> exp 9000 <= 10000)
    sig_below = base_signal.model_copy(update={"quantity": Decimal("90.0")})
    assert engine.evaluate(sig_below, base_context, policy).status == RiskDecisionStatus.APPROVED

    # Exactly at limit (qty=100, price=100 -> exp 10000)
    sig_at = base_signal.model_copy(update={"quantity": Decimal("100.0")})
    assert engine.evaluate(sig_at, base_context, policy).status == RiskDecisionStatus.APPROVED

    # Above limit (qty=101, price=100 -> exp 10100)
    sig_above = base_signal.model_copy(update={"quantity": Decimal("101.0")})
    decision = engine.evaluate(sig_above, base_context, policy)
    assert decision.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.MAX_EXPOSURE_EXCEEDED in decision.rejection_codes

    # Missing price
    sig_no_price = base_signal.model_copy(update={"proposed_entry_price": None})
    decision_np = engine.evaluate(sig_no_price, base_context, policy)
    assert decision_np.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.INSUFFICIENT_INFORMATION in decision_np.rejection_codes


def test_trade_risk(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()

    # Below maximum: price=100, stop=50 -> risk=50 * 9 = 450 <= 500
    sig_below = base_signal.model_copy(
        update={"quantity": Decimal("9.0"), "stop_loss": Decimal("50.0")}
    )
    assert (
        engine.evaluate(sig_below, base_context, base_policy).status == RiskDecisionStatus.APPROVED
    )

    # Exactly maximum: risk=50 * 10 = 500
    sig_at = base_signal.model_copy(
        update={"quantity": Decimal("10.0"), "stop_loss": Decimal("50.0")}
    )
    assert engine.evaluate(sig_at, base_context, base_policy).status == RiskDecisionStatus.APPROVED

    # Above maximum: risk=50 * 11 = 550
    policy = base_policy.model_copy(update={"max_order_quantity": Decimal("100.0")})
    sig_above = base_signal.model_copy(
        update={"quantity": Decimal("11.0"), "stop_loss": Decimal("50.0")}
    )
    decision = engine.evaluate(sig_above, base_context, policy)
    assert decision.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.MAX_RISK_PER_TRADE_EXCEEDED in decision.rejection_codes


def test_daily_loss(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()

    # Safe daily P&L (-1000 >= -2000 max_daily_loss)
    ctx_safe = base_context.model_copy(update={"daily_pnl": Decimal("-1000.0")})
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


def test_drawdown(base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy) -> None:
    engine = RiskEngine()

    # Safe drawdown: peak=20k, current=19k -> 5% (limit 10%)
    ctx_safe = base_context.model_copy(update={"current_equity": Decimal("19000.0")})
    assert engine.evaluate(base_signal, ctx_safe, base_policy).status == RiskDecisionStatus.APPROVED

    # Exactly at boundary: current=18k -> 10%
    ctx_at = base_context.model_copy(update={"current_equity": Decimal("18000.0")})
    assert engine.evaluate(base_signal, ctx_at, base_policy).status == RiskDecisionStatus.APPROVED

    # Beyond limit: current=17k -> 15%
    ctx_beyond = base_context.model_copy(update={"current_equity": Decimal("17000.0")})
    dec_beyond = engine.evaluate(base_signal, ctx_beyond, base_policy)
    assert dec_beyond.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.MAX_DRAWDOWN_EXCEEDED in dec_beyond.rejection_codes

    # Zero/negative peak equity
    ctx_bad_peak = base_context.model_copy(update={"peak_equity": Decimal("-10.0")})
    dec_bad = engine.evaluate(base_signal, ctx_bad_peak, base_policy)
    assert dec_bad.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.INVALID_RISK_CONTEXT in dec_bad.rejection_codes


def test_kill_switch(
    base_signal: Signal, base_context: RiskContext, base_policy: RiskPolicy
) -> None:
    engine = RiskEngine()

    # Via Context
    ctx_halted = base_context.model_copy(update={"trading_halted": True})
    dec_ctx = engine.evaluate(base_signal, ctx_halted, base_policy)
    assert dec_ctx.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.TRADING_HALTED in dec_ctx.rejection_codes

    # Via Policy
    pol_halted = base_policy.model_copy(update={"trading_halted": True})
    dec_pol = engine.evaluate(base_signal, base_context, pol_halted)
    assert dec_pol.status == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.TRADING_HALTED in dec_pol.rejection_codes


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
    assert "execute" not in source.lower()  # no execution
    assert " import ai" not in source.lower()
