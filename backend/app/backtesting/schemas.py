"""Pydantic schemas for the Backtesting Engine.

These schemas provide a pure data representation of a backtest request,
its progression, trades, equity curve, and final metrics.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import BacktestStatus, OrderSide


class BacktestRequest(BaseModel):
    """Configuration for a backtest run."""

    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(..., description="The ID of the strategy to test")
    strategy_version: str = Field(..., description="The version of the strategy to test")
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


class BacktestTradeRecord(BaseModel):
    """Deterministic record of a completed or closed simulated trade."""

    model_config = ConfigDict(frozen=True)

    trade_id: UUID
    strategy_id: str
    strategy_version: str
    symbol: str
    side: OrderSide
    quantity: Decimal

    entry_timestamp: datetime
    entry_price: Decimal

    exit_timestamp: datetime
    exit_price: Decimal

    gross_pnl: Decimal
    fees: Decimal
    slippage: Decimal
    net_pnl: Decimal
    return_percentage: Decimal


class BacktestEquityPoint(BaseModel):
    """Snapshot of account equity at a specific point in time."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    cash: Decimal
    position_value: Decimal
    equity: Decimal
    drawdown_pct: Decimal


class BacktestMetrics(BaseModel):
    """Calculated deterministic performance metrics."""

    model_config = ConfigDict(frozen=True)

    initial_capital: Decimal
    final_equity: Decimal
    total_return_pct: Decimal

    realized_pnl: Decimal
    unrealized_pnl: Decimal

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal

    max_drawdown_pct: Decimal
    peak_equity: Decimal
    minimum_equity: Decimal

    average_win: Decimal | None = None
    average_loss: Decimal | None = None
    largest_win: Decimal | None = None
    largest_loss: Decimal | None = None


class BacktestResult(BaseModel):
    """Complete, immutable output of a backtest run."""

    model_config = ConfigDict(frozen=True)

    backtest_id: UUID
    request: BacktestRequest
    status: BacktestStatus

    metrics: BacktestMetrics | None = None
    trades: list[BacktestTradeRecord] = Field(default_factory=list)
    equity_curve: list[BacktestEquityPoint] = Field(default_factory=list)

    error_message: str | None = None
