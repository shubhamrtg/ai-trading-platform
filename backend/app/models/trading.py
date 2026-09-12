import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import (
    AIRecommendation,
    OrderSide,
    OrderState,
    OrderType,
    RiskDecisionStatus,
    SignalType,
    TimeInForce,
)


class SignalModel(Base):
    """Database representation of a canonical strategy signal."""

    __tablename__ = "signals"

    signal_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    strategy_id: Mapped[str] = mapped_column(String, index=True)
    strategy_version: Mapped[str] = mapped_column(String)

    symbol: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    timeframe: Mapped[str] = mapped_column(String)

    side: Mapped[OrderSide] = mapped_column(String)
    signal_type: Mapped[SignalType] = mapped_column(String)

    proposed_entry_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)

    confidence: Mapped[float | None] = mapped_column(nullable=True)
    rationale: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AIAssessmentModel(Base):
    """Database representation of AI advisory output."""

    __tablename__ = "ai_assessments"

    assessment_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signals.signal_id"), index=True)

    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    input_context_hash: Mapped[str] = mapped_column(String)

    recommendation: Mapped[AIRecommendation] = mapped_column(String)
    confidence: Mapped[float] = mapped_column()
    rationale: Mapped[str] = mapped_column(String)

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RiskDecisionModel(Base):
    """Database representation of the Risk Engine's final authority."""

    __tablename__ = "risk_decisions"

    decision_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signals.signal_id"), index=True)

    status: Mapped[RiskDecisionStatus] = mapped_column(String)

    rejection_code: Mapped[str | None] = mapped_column(String, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    calculated_risk: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    calculated_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    risk_limit_applied: Mapped[str | None] = mapped_column(String, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderIntentModel(Base):
    """Database representation of an approved Order Intent."""

    __tablename__ = "order_intents"

    intent_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    originating_signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signals.signal_id"))
    risk_decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risk_decisions.decision_id"))

    account_id: Mapped[str] = mapped_column(String, index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)

    side: Mapped[OrderSide] = mapped_column(String)
    order_type: Mapped[OrderType] = mapped_column(String)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8))

    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)

    time_in_force: Mapped[TimeInForce] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    creation_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderModel(Base):
    """State machine of the actual order."""

    __tablename__ = "orders"

    order_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    intent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("order_intents.intent_id"), unique=True)
    broker_order_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)

    state: Mapped[OrderState] = mapped_column(String)

    filled_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0.0"))
    average_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)


class FillModel(Base):
    """Database representation of an execution fill."""

    __tablename__ = "fills"

    fill_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.order_id"), index=True)
    broker_fill_id: Mapped[str | None] = mapped_column(String, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8))

    fee: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0.0"))
    fee_asset: Mapped[str | None] = mapped_column(String, nullable=True)
    slippage: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
