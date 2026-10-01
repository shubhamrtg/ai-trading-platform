"""Paper trading persistence models.

Includes PaperSession and CashReservation models.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import PaperSessionState


class PaperSessionModel(Base):
    """Configuration and state for a paper trading session."""

    __tablename__ = "paper_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    account_id: Mapped[str] = mapped_column(String, index=True)

    strategy_id: Mapped[str] = mapped_column(String, index=True)
    strategy_version: Mapped[str] = mapped_column(String)

    symbol: Mapped[str] = mapped_column(String, index=True)
    timeframe: Mapped[str] = mapped_column(String)

    state: Mapped[PaperSessionState] = mapped_column(String)

    # Worker leasing for concurrency control
    worker_owner_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    worker_heartbeat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class CashReservationModel(Base):
    """Atomic cash reservation to prevent over-spending while order is pending."""

    __tablename__ = "cash_reservations"

    reservation_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper_sessions.session_id"), index=True
    )
    order_intent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("order_intents.intent_id"), unique=True
    )

    authorized_cash_requirement: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    creation_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    released_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
