import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import OrderSide, PositionState


class PositionModel(Base):
    """Database representation of a trading position."""

    __tablename__ = "positions"

    position_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    account_id: Mapped[str] = mapped_column(String, index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)

    state: Mapped[PositionState] = mapped_column(String)
    side: Mapped[OrderSide] = mapped_column(String)

    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0.0"))
    average_entry_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0.0"))

    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0.0"))
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0.0"))

    strategy_id: Mapped[str | None] = mapped_column(String, nullable=True)
    entry_signal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("signals.signal_id"), nullable=True
    )

    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)


class PortfolioSnapshotModel(Base):
    """Database representation of the portfolio state at a point in time."""

    __tablename__ = "portfolio_snapshots"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    account_id: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    cash: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    available_cash: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    equity: Mapped[Decimal] = mapped_column(Numeric(24, 8))

    total_realized_pnl: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0.0"))
    total_unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0.0"))

    total_exposure: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0.0"))
    reserved_capital: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0.0"))
