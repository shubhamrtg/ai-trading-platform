"""Trading pipeline persistence models.

Models follow the canonical trading pipeline:
  Signal → AIAssessment → RiskDecision → OrderIntent → Order → Fill

Design decisions:
- All financial values use Numeric(24, 8) for exact decimal precision.
- All timestamps use DateTime(timezone=True) for UTC consistency.
- Enum fields are stored as String columns (not PostgreSQL native enums).
- correlation_id links all objects in a single trading decision chain.
- Foreign keys enforce the mandatory pipeline relationships.
- Order is self-contained (denormalized from OrderIntent) for operational queries.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, event, inspect
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.transitions import validate_order_transition
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
    """A strategy-generated trading signal. A proposal, NOT an executable order."""

    __tablename__ = "signals"

    signal_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    correlation_id: Mapped[uuid.UUID] = mapped_column(index=True, default=uuid.uuid4)

    strategy_id: Mapped[str] = mapped_column(String, index=True)
    strategy_version: Mapped[str] = mapped_column(String)

    symbol: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    timeframe: Mapped[str] = mapped_column(String)

    side: Mapped[OrderSide] = mapped_column(String)
    order_type: Mapped[OrderType] = mapped_column(String, default=OrderType.MARKET)
    signal_type: Mapped[SignalType] = mapped_column(String)

    proposed_entry_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)

    confidence: Mapped[float | None] = mapped_column(nullable=True)
    rationale: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AIAssessmentModel(Base):
    """AI advisory output. Advisory only — never authoritative for execution."""

    __tablename__ = "ai_assessments"

    assessment_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    correlation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signals.signal_id"), index=True)

    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    input_context_hash: Mapped[str] = mapped_column(String)

    recommendation: Mapped[AIRecommendation] = mapped_column(String)
    confidence: Mapped[float] = mapped_column()
    rationale: Mapped[str] = mapped_column(String)

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RiskDecisionModel(Base):
    """The Risk Engine's final authority over a trading decision."""

    __tablename__ = "risk_decisions"

    decision_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    correlation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signals.signal_id"), index=True)

    status: Mapped[RiskDecisionStatus] = mapped_column(String)
    trading_mode: Mapped[str] = mapped_column(String, default='PAPER')

    rejection_code: Mapped[str | None] = mapped_column(String, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    calculated_risk: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    calculated_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    risk_limit_applied: Mapped[str | None] = mapped_column(String, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderIntentModel(Base):
    """Risk-approved request for the execution engine.

    Cannot exist without a valid RiskDecision (enforced by FK).
    The idempotency_key prevents duplicate execution at the DB level.
    """

    __tablename__ = "order_intents"

    intent_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    correlation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    originating_signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signals.signal_id"))
    risk_decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risk_decisions.decision_id"))

    account_id: Mapped[str] = mapped_column(String, index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)

    side: Mapped[OrderSide] = mapped_column(String)
    order_type: Mapped[OrderType] = mapped_column(String, default=OrderType.MARKET)
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
    """Actual order tracked by the execution engine / broker.

    Self-contained for operational queries — key fields are denormalized
    from OrderIntent so that order queries don't require JOINs.
    """

    __tablename__ = "orders"

    order_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    correlation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    intent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("order_intents.intent_id"), unique=True)
    broker_order_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)

    # Denormalized from OrderIntent for self-contained operational queries
    symbol: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[OrderSide] = mapped_column(String)
    order_type: Mapped[OrderType] = mapped_column(String, default=OrderType.MARKET)
    order_type: Mapped[OrderType] = mapped_column(String)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8))

    state: Mapped[OrderState] = mapped_column(String, index=True)

    filled_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0.0"))
    average_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class FillModel(Base):
    """A single execution fill against an order.

    One Order can have multiple Fills (partial fills).
    """

    __tablename__ = "fills"

    fill_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    correlation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.order_id"), index=True)
    broker_fill_id: Mapped[str | None] = mapped_column(String, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8))

    fee: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0.0"))
    fee_asset: Mapped[str | None] = mapped_column(String, nullable=True)
    slippage: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)


@event.listens_for(OrderModel, "before_update")
def enforce_order_state_transitions(mapper: Any, connection: Any, target: OrderModel) -> None:
    """Enforce that Order state transitions follow the authoritative state machine."""
    state = inspect(target)
    if not state.has_identity:
        return

    status_history = state.attrs.state.history
    if status_history.has_changes():
        if status_history.deleted:
            original_status_str = status_history.deleted[0]
        else:
            original_status_str = state.committed_state.get("state")
            if not original_status_str:
                return  # Unloaded and unknown original state

        new_status_str = target.state

        # Convert strings back to enums for validation
        original_status = OrderState(original_status_str)
        new_status = OrderState(new_status_str)

        validate_order_transition(original_status, new_status)
