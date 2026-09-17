import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import BacktestStatus


class BacktestRunModel(Base):
    """Database model for a backtest run."""

    __tablename__ = "backtest_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    correlation_id: Mapped[uuid.UUID] = mapped_column(index=True, default=uuid.uuid4)
    idempotency_key: Mapped[str | None] = mapped_column(
        String, unique=True, index=True, nullable=True
    )

    status: Mapped[BacktestStatus] = mapped_column(String, index=True)

    strategy_id: Mapped[str] = mapped_column(String, index=True)
    strategy_version: Mapped[str] = mapped_column(String)

    symbol: Mapped[str] = mapped_column(String, index=True)
    timeframe: Mapped[str] = mapped_column(String)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    initial_capital: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    commission_pct: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    slippage_pct: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Result Metrics
    final_equity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    total_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    total_trades: Mapped[int | None] = mapped_column(nullable=True)
    winning_trades: Mapped[int | None] = mapped_column(nullable=True)
    losing_trades: Mapped[int | None] = mapped_column(nullable=True)
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    max_drawdown_pct: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    peak_equity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    minimum_equity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    average_win: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    average_loss: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    largest_win: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    largest_loss: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)

    # Detailed results
    trades_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    equity_curve_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # Metadata
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
