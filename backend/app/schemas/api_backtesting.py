"""Pydantic schemas for Backtesting API boundary.

These separate the HTTP contract from the internal domain schemas.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.backtesting.schemas import BacktestEquityPoint, BacktestTradeRecord
from app.models.enums import BacktestStatus


class BacktestCreateRequest(BaseModel):
    """API request body to create and start a backtest run."""

    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(..., description="The ID of the strategy to test")
    strategy_version: str = Field(..., description="The precise version of the strategy to test")
    symbol: str = Field(..., description="The instrument symbol")
    timeframe: str = Field(..., description="The timeframe")
    start_time: datetime = Field(..., description="Historical start time in UTC")
    end_time: datetime = Field(..., description="Historical end time in UTC")

    initial_capital: Decimal = Field(default=Decimal("100000.0"), gt=0)
    commission_pct: Decimal = Field(
        default=Decimal("0.0"), ge=0, description="Commission per trade (percentage)"
    )
    slippage_pct: Decimal = Field(
        default=Decimal("0.0"), ge=0, description="Slippage per trade (percentage)"
    )

    parameters: dict[str, Any] = Field(default_factory=dict, description="Strategy parameters")

    idempotency_key: str | None = Field(None, description="Optional key to prevent duplicate runs")


class BacktestListResponse(BaseModel):
    """API response for a summary list of backtests."""

    model_config = ConfigDict(from_attributes=True)

    run_id: UUID
    status: BacktestStatus
    strategy_id: str
    strategy_version: str
    symbol: str
    timeframe: str
    start_time: datetime
    end_time: datetime
    created_at: datetime
    completed_at: datetime | None = None

    # Selected key metrics for lightweight display
    final_equity: Decimal | None = None
    total_return_pct: Decimal | None = None
    realized_pnl: Decimal | None = None
    total_trades: int | None = None


class BacktestDetailResponse(BacktestListResponse):
    """API response for a detailed backtest, including metrics, trades, and equity curve."""

    initial_capital: Decimal
    commission_pct: Decimal
    slippage_pct: Decimal
    parameters: dict[str, Any]

    # Detailed metrics
    unrealized_pnl: Decimal | None = None
    winning_trades: int | None = None
    losing_trades: int | None = None
    win_rate: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    peak_equity: Decimal | None = None
    minimum_equity: Decimal | None = None
    average_win: Decimal | None = None
    average_loss: Decimal | None = None
    largest_win: Decimal | None = None
    largest_loss: Decimal | None = None

    # Error message if failed
    error_message: str | None = None

    # Large payloads (using existing domain schemas since they match our exact output needs)
    trades: list[BacktestTradeRecord] = Field(default_factory=list)
    equity_curve: list[BacktestEquityPoint] = Field(default_factory=list)


class BacktestListPaginated(BaseModel):
    items: list[BacktestListResponse]
    total: int
