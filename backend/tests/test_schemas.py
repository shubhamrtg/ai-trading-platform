import pytest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from pydantic import ValidationError

from app.models.enums import OrderSide, OrderType, TimeInForce, SignalType, RiskDecisionStatus
from app.schemas.market_data import Candle
from app.schemas.signal import Signal
from app.schemas.order import OrderIntent
from app.schemas.risk import RiskDecision


def test_candle_schema_validation():
    # Valid candle
    candle = Candle(
        symbol="BTC-USD",
        timestamp=datetime.now(timezone.utc),
        timeframe="1h",
        open=Decimal("50000.0"),
        high=Decimal("51000.0"),
        low=Decimal("49000.0"),
        close=Decimal("50500.0"),
        volume=Decimal("100.5")
    )
    assert candle.symbol == "BTC-USD"
    assert candle.volume > 0

    # Invalid volume
    with pytest.raises(ValidationError):
        Candle(
            symbol="BTC-USD",
            timestamp=datetime.now(timezone.utc),
            timeframe="1h",
            open=Decimal("50000.0"),
            high=Decimal("51000.0"),
            low=Decimal("49000.0"),
            close=Decimal("50500.0"),
            volume=Decimal("-10.0")  # Invalid
        )

def test_signal_schema():
    signal = Signal(
        signal_id=uuid4(),
        strategy_id="test_strat",
        strategy_version="1.0.0",
        symbol="ETH-USD",
        timestamp=datetime.now(timezone.utc),
        timeframe="5m",
        side=OrderSide.BUY,
        signal_type=SignalType.ENTRY
    )
    assert signal.side == OrderSide.BUY

def test_risk_decision_schema():
    decision = RiskDecision(
        decision_id=uuid4(),
        signal_id=uuid4(),
        status=RiskDecisionStatus.APPROVED,
        calculated_quantity=Decimal("1.5"),
        timestamp=datetime.now(timezone.utc)
    )
    assert decision.status == RiskDecisionStatus.APPROVED

def test_order_intent_schema():
    # quantity must be > 0
    with pytest.raises(ValidationError):
        OrderIntent(
            intent_id=uuid4(),
            originating_signal_id=uuid4(),
            risk_decision_id=uuid4(),
            account_id="test_acc",
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.0"),  # Invalid, must be > 0
            idempotency_key="test_key_123",
            creation_timestamp=datetime.now(timezone.utc)
        )
