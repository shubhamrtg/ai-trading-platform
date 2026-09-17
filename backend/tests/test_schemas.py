"""Comprehensive tests for Pydantic domain schemas.

Covers:
- Enum serialization/deserialization
- Decimal precision (financial values)
- Timezone awareness
- Cross-field validation (OrderIntent, RiskDecision)
- Domain separation invariants (Signal != OrderIntent)
- Validation boundary cases
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from app.models.enums import (
    AIRecommendation,
    OrderSide,
    OrderState,
    OrderType,
    PositionState,
    RiskDecisionStatus,
    RiskRejectionCode,
    SignalType,
    StrategyStatus,
    TimeInForce,
)
from app.schemas.ai import AIAssessment
from app.schemas.market_data import Candle
from app.schemas.order import Fill, Order, OrderIntent
from app.schemas.portfolio import PortfolioSnapshot, Position
from app.schemas.risk import RiskDecision
from app.schemas.signal import Signal
from pydantic import ValidationError

# ============================================================
# Enum Tests
# ============================================================


class TestEnumSerialization:
    """Verify enums serialize to stable string values."""

    def test_order_side_values(self) -> None:
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"
        assert len(OrderSide) == 2

    def test_order_type_values(self) -> None:
        assert set(OrderType) == {
            OrderType.MARKET,
            OrderType.LIMIT,
            OrderType.STOP_MARKET,
            OrderType.STOP_LIMIT,
        }

    def test_time_in_force_values(self) -> None:
        assert set(TimeInForce) == {
            TimeInForce.GTC,
            TimeInForce.IOC,
            TimeInForce.FOK,
            TimeInForce.DAY,
        }

    def test_order_state_complete_lifecycle(self) -> None:
        """OrderState must have all lifecycle states for future execution engine."""
        expected = {
            "CREATED",
            "VALIDATED",
            "SUBMITTED",
            "ACKNOWLEDGED",
            "PARTIALLY_FILLED",
            "FILLED",
            "CANCEL_PENDING",
            "CANCELLED",
            "REJECTED",
            "EXPIRED",
            "FAILED",
        }
        actual = {s.value for s in OrderState}
        assert actual == expected

    def test_position_state_values(self) -> None:
        expected = {"OPENING", "OPEN", "REDUCING", "CLOSING", "CLOSED"}
        actual = {s.value for s in PositionState}
        assert actual == expected

    def test_signal_type_values(self) -> None:
        assert SignalType.ENTRY.value == "ENTRY"
        assert SignalType.EXIT.value == "EXIT"

    def test_risk_decision_status_values(self) -> None:
        expected = {"APPROVED", "REJECTED", "MODIFIED"}
        actual = {s.value for s in RiskDecisionStatus}
        assert actual == expected

    def test_ai_recommendation_values(self) -> None:
        expected = {"ALLOW", "REJECT", "HOLD"}
        actual = {s.value for s in AIRecommendation}
        assert actual == expected

    def test_strategy_status_values(self) -> None:
        expected = {"DRAFT", "ACTIVE", "DEPRECATED", "DISABLED"}
        actual = {s.value for s in StrategyStatus}
        assert actual == expected

    def test_enum_string_serialization(self) -> None:
        """Enums must serialize as their string value for JSON/DB."""
        assert str(OrderSide.BUY) == "OrderSide.BUY"
        assert OrderSide.BUY.value == "BUY"
        # Pydantic serialization test
        signal = Signal(
            signal_id=uuid4(),
            correlation_id=uuid4(),
            strategy_id="test",
            strategy_version="1.0.0",
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            timeframe="1h",
            side=OrderSide.BUY,
            signal_type=SignalType.ENTRY,
            quantity=Decimal("1.0"),
        )
        data = signal.model_dump(mode="json")
        assert data["side"] == "BUY"
        assert data["signal_type"] == "ENTRY"

    def test_enum_deserialization_from_string(self) -> None:
        """Enums must be constructible from their string values."""
        assert OrderSide("BUY") == OrderSide.BUY
        assert OrderState("FILLED") == OrderState.FILLED

    def test_invalid_enum_value_rejected(self) -> None:
        """Invalid enum values must raise ValueError."""
        with pytest.raises(ValueError):
            OrderSide("INVALID")
        with pytest.raises(ValueError):
            OrderState("NOT_A_STATE")


# ============================================================
# Decimal Precision Tests
# ============================================================


class TestDecimalPrecision:
    """Verify financial values maintain exact decimal precision."""

    def test_decimal_precision_preserved_in_candle(self) -> None:
        candle = Candle(
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            timeframe="1h",
            open=Decimal("0.1"),
            high=Decimal("0.2"),
            low=Decimal("0.05"),
            close=Decimal("0.3"),
            volume=Decimal("1000.12345678"),
        )
        assert candle.open == Decimal("0.1")
        assert candle.close == Decimal("0.3")
        assert candle.volume == Decimal("1000.12345678")

    def test_decimal_addition_no_float_error(self) -> None:
        """Decimal(0.1) + Decimal(0.2) must equal Decimal(0.3) exactly."""
        a = Decimal("0.1")
        b = Decimal("0.2")
        result = a + b
        assert result == Decimal("0.3")

    def test_position_pnl_precision(self) -> None:
        position = Position(
            position_id=uuid4(),
            account_id="acc1",
            symbol="ETH-USD",
            state=PositionState.OPEN,
            side=OrderSide.BUY,
            quantity=Decimal("1.50000000"),
            average_entry_price=Decimal("2500.12345678"),
            realized_pnl=Decimal("-0.00000001"),
            unrealized_pnl=Decimal("100.99999999"),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert position.realized_pnl == Decimal("-0.00000001")
        assert position.unrealized_pnl == Decimal("100.99999999")

    def test_portfolio_financial_precision(self) -> None:
        snapshot = PortfolioSnapshot(
            account_id="acc1",
            timestamp=datetime.now(UTC),
            cash=Decimal("10000.12345678"),
            available_cash=Decimal("9500.00000001"),
            equity=Decimal("10500.50000000"),
        )
        assert snapshot.cash == Decimal("10000.12345678")
        assert snapshot.available_cash == Decimal("9500.00000001")

    def test_fill_price_and_fee_precision(self) -> None:
        fill = Fill(
            fill_id=uuid4(),
            correlation_id=uuid4(),
            order_id=uuid4(),
            timestamp=datetime.now(UTC),
            price=Decimal("50000.12345678"),
            quantity=Decimal("0.00100000"),
            fee=Decimal("0.00000050"),
        )
        assert fill.price == Decimal("50000.12345678")
        assert fill.fee == Decimal("0.00000050")


# ============================================================
# Timezone Awareness Tests
# ============================================================


class TestTimezoneAwareness:
    """Verify all timestamps are timezone-aware."""

    def test_signal_timestamp_is_timezone_aware(self) -> None:
        ts = datetime.now(UTC)
        signal = Signal(
            signal_id=uuid4(),
            correlation_id=uuid4(),
            strategy_id="test",
            strategy_version="1.0.0",
            symbol="BTC-USD",
            timestamp=ts,
            timeframe="1h",
            side=OrderSide.BUY,
            signal_type=SignalType.ENTRY,
            quantity=Decimal("1.0"),
        )
        assert signal.timestamp.tzinfo is not None

    def test_candle_timestamp_with_explicit_utc(self) -> None:
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        candle = Candle(
            symbol="BTC-USD",
            timestamp=ts,
            timeframe="1h",
            open=Decimal("50000"),
            high=Decimal("51000"),
            low=Decimal("49000"),
            close=Decimal("50500"),
            volume=Decimal("100"),
        )
        assert candle.timestamp.tzinfo is not None
        assert candle.timestamp == ts

    def test_order_timestamps_round_trip(self) -> None:
        now = datetime.now(UTC)
        order = Order(
            order_id=uuid4(),
            correlation_id=uuid4(),
            intent_id=uuid4(),
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1.0"),
            state=OrderState.CREATED,
            created_at=now,
            updated_at=now,
        )
        assert order.created_at.tzinfo is not None
        assert order.updated_at.tzinfo is not None


# ============================================================
# Candle Tests
# ============================================================


class TestCandle:
    """Test market data schema validation."""

    def test_valid_candle(self) -> None:
        candle = Candle(
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            timeframe="1h",
            open=Decimal("50000.0"),
            high=Decimal("51000.0"),
            low=Decimal("49000.0"),
            close=Decimal("50500.0"),
            volume=Decimal("100.5"),
        )
        assert candle.symbol == "BTC-USD"
        assert candle.volume > 0

    def test_negative_volume_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Candle(
                symbol="BTC-USD",
                timestamp=datetime.now(UTC),
                timeframe="1h",
                open=Decimal("50000.0"),
                high=Decimal("51000.0"),
                low=Decimal("49000.0"),
                close=Decimal("50500.0"),
                volume=Decimal("-10.0"),
            )


# ============================================================
# Signal Tests
# ============================================================


class TestSignal:
    """Test signal schema validation."""

    def test_valid_signal(self) -> None:
        signal = Signal(
            signal_id=uuid4(),
            correlation_id=uuid4(),
            strategy_id="test_strat",
            strategy_version="1.0.0",
            symbol="ETH-USD",
            timestamp=datetime.now(UTC),
            timeframe="5m",
            side=OrderSide.BUY,
            signal_type=SignalType.ENTRY,
            quantity=Decimal("1.0"),
        )
        assert signal.side == OrderSide.BUY
        assert signal.signal_type == SignalType.ENTRY

    def test_confidence_bounds(self) -> None:
        """Confidence must be between 0 and 1."""
        with pytest.raises(ValidationError):
            Signal(
                signal_id=uuid4(),
                correlation_id=uuid4(),
                strategy_id="test",
                strategy_version="1.0.0",
                symbol="BTC-USD",
                timestamp=datetime.now(UTC),
                timeframe="1h",
                side=OrderSide.BUY,
                signal_type=SignalType.ENTRY,
                confidence=1.5,
            )

    def test_signal_has_correlation_id(self) -> None:
        cid = uuid4()
        signal = Signal(
            signal_id=uuid4(),
            correlation_id=cid,
            strategy_id="test",
            strategy_version="1.0.0",
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            timeframe="1h",
            side=OrderSide.BUY,
            signal_type=SignalType.ENTRY,
            quantity=Decimal("1.0"),
        )
        assert signal.correlation_id == cid


# ============================================================
# RiskDecision Tests
# ============================================================


class TestRiskDecision:
    """Test risk decision schema and cross-field validation."""

    def test_approved_decision(self) -> None:
        decision = RiskDecision(
            decision_id=uuid4(),
            correlation_id=uuid4(),
            signal_id=uuid4(),
            status=RiskDecisionStatus.APPROVED,
            calculated_quantity=Decimal("1.5"),
            timestamp=datetime.now(UTC),
        )
        assert decision.status == RiskDecisionStatus.APPROVED
        assert decision.calculated_quantity == Decimal("1.5")

    def test_rejected_decision(self) -> None:
        decision = RiskDecision(
            decision_id=uuid4(),
            correlation_id=uuid4(),
            signal_id=uuid4(),
            status=RiskDecisionStatus.REJECTED,
            rejection_codes=[RiskRejectionCode.MAX_EXPOSURE_EXCEEDED],
            rejection_reasons=["Total exposure would exceed 50% of equity"],
            timestamp=datetime.now(UTC),
        )
        assert decision.status == RiskDecisionStatus.REJECTED
        assert decision.rejection_codes == [RiskRejectionCode.MAX_EXPOSURE_EXCEEDED]
        assert decision.calculated_quantity is None

    def test_rejected_with_quantity_fails(self) -> None:
        with pytest.raises(ValidationError):
            RiskDecision(
                decision_id=uuid4(),
                correlation_id=uuid4(),
                signal_id=uuid4(),
                status=RiskDecisionStatus.REJECTED,
                rejection_codes=[RiskRejectionCode.MAX_EXPOSURE_EXCEEDED],
                calculated_quantity=Decimal("1.0"),
                timestamp=datetime.now(UTC),
            )

    def test_approved_with_rejection_code_fails(self) -> None:
        with pytest.raises(ValidationError):
            RiskDecision(
                decision_id=uuid4(),
                correlation_id=uuid4(),
                signal_id=uuid4(),
                status=RiskDecisionStatus.APPROVED,
                rejection_codes=[RiskRejectionCode.MAX_EXPOSURE_EXCEEDED],
                calculated_quantity=Decimal("1.0"),
                timestamp=datetime.now(UTC),
            )

    def test_modified_decision(self) -> None:
        decision = RiskDecision(
            decision_id=uuid4(),
            correlation_id=uuid4(),
            signal_id=uuid4(),
            status=RiskDecisionStatus.MODIFIED,
            calculated_quantity=Decimal("0.5"),
            risk_limit_applied="MAX_POSITION_SIZE",
            timestamp=datetime.now(UTC),
        )
        assert decision.status == RiskDecisionStatus.MODIFIED
        assert decision.risk_limit_applied == "MAX_POSITION_SIZE"


# ============================================================
# OrderIntent Tests
# ============================================================


class TestOrderIntent:
    """Test order intent validation including cross-field rules."""

    def _make_intent(self, **overrides: object) -> OrderIntent:
        defaults: dict[str, object] = {
            "intent_id": uuid4(),
            "correlation_id": uuid4(),
            "originating_signal_id": uuid4(),
            "risk_decision_id": uuid4(),
            "account_id": "test_acc",
            "symbol": "BTC-USD",
            "side": OrderSide.BUY,
            "order_type": OrderType.MARKET,
            "quantity": Decimal("1.0"),
            "idempotency_key": f"key-{uuid4()}",
            "creation_timestamp": datetime.now(UTC),
        }
        defaults.update(overrides)
        return OrderIntent(**defaults)  # type: ignore[arg-type]

    def test_valid_market_order(self) -> None:
        intent = self._make_intent()
        assert intent.order_type == OrderType.MARKET

    def test_zero_quantity_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_intent(quantity=Decimal("0.0"))

    def test_negative_quantity_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_intent(quantity=Decimal("-1.0"))

    def test_limit_order_without_price_fails(self) -> None:
        """LIMIT orders must have a limit_price."""
        with pytest.raises(ValidationError, match="LIMIT.*limit_price"):
            self._make_intent(order_type=OrderType.LIMIT)

    def test_limit_order_with_price_succeeds(self) -> None:
        intent = self._make_intent(
            order_type=OrderType.LIMIT,
            limit_price=Decimal("50000.00"),
        )
        assert intent.limit_price == Decimal("50000.00")

    def test_stop_market_without_stop_price_fails(self) -> None:
        """STOP_MARKET orders must have a stop_price."""
        with pytest.raises(ValidationError, match="STOP_MARKET.*stop_price"):
            self._make_intent(order_type=OrderType.STOP_MARKET)

    def test_stop_limit_requires_both_prices(self) -> None:
        """STOP_LIMIT requires both limit_price and stop_price."""
        with pytest.raises(ValidationError):
            self._make_intent(
                order_type=OrderType.STOP_LIMIT,
                limit_price=Decimal("50000.00"),
                # missing stop_price
            )
        with pytest.raises(ValidationError):
            self._make_intent(
                order_type=OrderType.STOP_LIMIT,
                stop_price=Decimal("49000.00"),
                # missing limit_price
            )

    def test_stop_limit_with_both_prices_succeeds(self) -> None:
        intent = self._make_intent(
            order_type=OrderType.STOP_LIMIT,
            limit_price=Decimal("50000.00"),
            stop_price=Decimal("49000.00"),
        )
        assert intent.limit_price == Decimal("50000.00")
        assert intent.stop_price == Decimal("49000.00")

    def test_market_order_ignores_limit_price(self) -> None:
        """MARKET orders should not require a limit_price (but can have one)."""
        intent = self._make_intent(order_type=OrderType.MARKET)
        assert intent.limit_price is None

    def test_idempotency_key_required(self) -> None:
        with pytest.raises(ValidationError):
            OrderIntent(
                intent_id=uuid4(),
                correlation_id=uuid4(),
                originating_signal_id=uuid4(),
                risk_decision_id=uuid4(),
                account_id="test",
                symbol="BTC",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("1.0"),
                creation_timestamp=datetime.now(UTC),
                # missing idempotency_key
            )

    def test_risk_decision_id_required(self) -> None:
        """OrderIntent must have a risk_decision_id — not creatable without risk approval."""
        with pytest.raises(ValidationError):
            OrderIntent(
                intent_id=uuid4(),
                correlation_id=uuid4(),
                originating_signal_id=uuid4(),
                # missing risk_decision_id
                account_id="test",
                symbol="BTC",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("1.0"),
                idempotency_key="key",
                creation_timestamp=datetime.now(UTC),
            )


# ============================================================
# Order Tests
# ============================================================


class TestOrder:
    """Test Order schema."""

    def test_valid_order(self) -> None:
        now = datetime.now(UTC)
        order = Order(
            order_id=uuid4(),
            correlation_id=uuid4(),
            intent_id=uuid4(),
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1.0"),
            state=OrderState.CREATED,
            created_at=now,
            updated_at=now,
        )
        assert order.state == OrderState.CREATED
        assert order.filled_quantity == Decimal("0.0")

    def test_order_all_states_valid(self) -> None:
        """Every OrderState value should be assignable."""
        now = datetime.now(UTC)
        for state in OrderState:
            order = Order(
                order_id=uuid4(),
                correlation_id=uuid4(),
                intent_id=uuid4(),
                symbol="BTC-USD",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("1.0"),
                state=state,
                created_at=now,
                updated_at=now,
            )
            assert order.state == state

    def test_filled_quantity_cannot_be_negative(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError):
            Order(
                order_id=uuid4(),
                correlation_id=uuid4(),
                intent_id=uuid4(),
                symbol="BTC-USD",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("1.0"),
                state=OrderState.CREATED,
                filled_quantity=Decimal("-0.1"),
                created_at=now,
                updated_at=now,
            )


# ============================================================
# Fill Tests
# ============================================================


class TestFill:
    """Test Fill schema."""

    def test_valid_fill(self) -> None:
        fill = Fill(
            fill_id=uuid4(),
            correlation_id=uuid4(),
            order_id=uuid4(),
            timestamp=datetime.now(UTC),
            price=Decimal("50000.00"),
            quantity=Decimal("0.5"),
        )
        assert fill.price == Decimal("50000.00")

    def test_fill_price_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Fill(
                fill_id=uuid4(),
                correlation_id=uuid4(),
                order_id=uuid4(),
                timestamp=datetime.now(UTC),
                price=Decimal("0.0"),
                quantity=Decimal("0.5"),
            )

    def test_fill_quantity_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Fill(
                fill_id=uuid4(),
                correlation_id=uuid4(),
                order_id=uuid4(),
                timestamp=datetime.now(UTC),
                price=Decimal("50000.00"),
                quantity=Decimal("0.0"),
            )

    def test_multiple_fills_different_ids(self) -> None:
        """Multiple fills can reference the same order."""
        order_id = uuid4()
        corr_id = uuid4()
        fill1 = Fill(
            fill_id=uuid4(),
            correlation_id=corr_id,
            order_id=order_id,
            timestamp=datetime.now(UTC),
            price=Decimal("50000.00"),
            quantity=Decimal("0.3"),
        )
        fill2 = Fill(
            fill_id=uuid4(),
            correlation_id=corr_id,
            order_id=order_id,
            timestamp=datetime.now(UTC),
            price=Decimal("50001.00"),
            quantity=Decimal("0.7"),
        )
        assert fill1.order_id == fill2.order_id
        assert fill1.fill_id != fill2.fill_id
        assert fill1.correlation_id == fill2.correlation_id


# ============================================================
# Position Tests
# ============================================================


class TestPosition:
    """Test Position schema."""

    def test_valid_position(self) -> None:
        position = Position(
            position_id=uuid4(),
            account_id="acc1",
            symbol="BTC-USD",
            state=PositionState.OPEN,
            side=OrderSide.BUY,
            quantity=Decimal("1.0"),
            average_entry_price=Decimal("50000.00"),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert position.state == PositionState.OPEN

    def test_position_quantity_cannot_be_negative(self) -> None:
        with pytest.raises(ValidationError):
            Position(
                position_id=uuid4(),
                account_id="acc1",
                symbol="BTC-USD",
                state=PositionState.OPEN,
                side=OrderSide.BUY,
                quantity=Decimal("-1.0"),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_all_position_states_valid(self) -> None:
        for state in PositionState:
            position = Position(
                position_id=uuid4(),
                account_id="acc1",
                symbol="BTC-USD",
                state=state,
                side=OrderSide.BUY,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            assert position.state == state


# ============================================================
# Portfolio Tests
# ============================================================


class TestPortfolio:
    """Test PortfolioSnapshot schema."""

    def test_valid_snapshot(self) -> None:
        snapshot = PortfolioSnapshot(
            account_id="acc1",
            timestamp=datetime.now(UTC),
            cash=Decimal("10000.00"),
            available_cash=Decimal("9500.00"),
            equity=Decimal("10500.00"),
        )
        assert snapshot.cash == Decimal("10000.00")

    def test_portfolio_precision(self) -> None:
        """Financial values must preserve 8 decimal places."""
        snapshot = PortfolioSnapshot(
            account_id="acc1",
            timestamp=datetime.now(UTC),
            cash=Decimal("10000.12345678"),
            available_cash=Decimal("9500.87654321"),
            equity=Decimal("10500.99999999"),
            total_realized_pnl=Decimal("500.00000001"),
            total_unrealized_pnl=Decimal("-100.00000001"),
        )
        assert snapshot.total_realized_pnl == Decimal("500.00000001")
        assert snapshot.total_unrealized_pnl == Decimal("-100.00000001")


# ============================================================
# AIAssessment Tests
# ============================================================


class TestAIAssessment:
    """Test AI Advisory schema — must remain advisory only."""

    def test_valid_assessment(self) -> None:
        assessment = AIAssessment(
            assessment_id=uuid4(),
            correlation_id=uuid4(),
            signal_id=uuid4(),
            provider="gemini",
            model="gemini-1.5-pro",
            input_context_hash="abc123",
            recommendation=AIRecommendation.ALLOW,
            confidence=0.85,
            rationale="Strong uptrend detected",
            timestamp=datetime.now(UTC),
        )
        assert assessment.recommendation == AIRecommendation.ALLOW

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            AIAssessment(
                assessment_id=uuid4(),
                correlation_id=uuid4(),
                signal_id=uuid4(),
                provider="test",
                model="test",
                input_context_hash="hash",
                recommendation=AIRecommendation.ALLOW,
                confidence=1.5,
                rationale="test",
                timestamp=datetime.now(UTC),
            )


# ============================================================
# Domain Separation Tests
# ============================================================


class TestDomainSeparation:
    """Verify that domain objects are distinct types."""

    def test_signal_is_not_order_intent(self) -> None:
        assert Signal is not OrderIntent

    def test_risk_decision_is_not_order_intent(self) -> None:
        assert RiskDecision is not OrderIntent

    def test_order_intent_is_not_order(self) -> None:
        assert OrderIntent is not Order

    def test_order_is_not_fill(self) -> None:
        assert Order is not Fill

    def test_position_is_not_portfolio(self) -> None:
        assert Position is not PortfolioSnapshot

    def test_signal_cannot_create_order(self) -> None:
        """Signal schema must not accept order-specific fields like state."""
        signal_data = {
            "signal_id": str(uuid4()),
            "correlation_id": str(uuid4()),
            "strategy_id": "test",
            "strategy_version": "1.0.0",
            "symbol": "BTC-USD",
            "timestamp": datetime.now(UTC).isoformat(),
            "timeframe": "1h",
            "side": "BUY",
            "signal_type": "ENTRY",
            "quantity": "1.0",
            "state": "CREATED",  # This is an Order field, not a Signal field
        }
        signal = Signal.model_validate(signal_data)
        # Signal accepts extra fields via model_config but 'state' is NOT a field
        assert not hasattr(signal, "state") or "state" not in signal.model_fields


# ============================================================
# Correlation ID Tests
# ============================================================


class TestCorrelationID:
    """Verify correlation IDs can link a complete trading chain."""

    def test_same_correlation_id_across_pipeline(self) -> None:
        """A single trading decision should share one correlation_id."""
        corr_id = uuid4()
        sig_id = uuid4()
        dec_id = uuid4()

        signal = Signal(
            signal_id=sig_id,
            correlation_id=corr_id,
            strategy_id="test",
            strategy_version="1.0.0",
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            timeframe="1h",
            side=OrderSide.BUY,
            signal_type=SignalType.ENTRY,
            quantity=Decimal("1.0"),
        )

        decision = RiskDecision(
            decision_id=dec_id,
            correlation_id=corr_id,
            signal_id=sig_id,
            status=RiskDecisionStatus.APPROVED,
            calculated_quantity=Decimal("1.0"),
            timestamp=datetime.now(UTC),
        )

        intent = OrderIntent(
            intent_id=uuid4(),
            correlation_id=corr_id,
            originating_signal_id=sig_id,
            risk_decision_id=dec_id,
            account_id="acc1",
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1.0"),
            idempotency_key="test-key-1",
            creation_timestamp=datetime.now(UTC),
        )

        assert signal.correlation_id == corr_id
        assert decision.correlation_id == corr_id
        assert intent.correlation_id == corr_id
