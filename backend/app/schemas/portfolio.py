from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderSide, PositionState


class Position(BaseModel):
    """
    State of a specific trading position.
    Updated strictly based on Fills.
    """

    model_config = ConfigDict(from_attributes=True)

    position_id: UUID
    account_id: str
    symbol: str

    state: PositionState
    side: OrderSide

    quantity: Decimal = Field(default=Decimal("0.0"), ge=0)
    average_entry_price: Decimal = Field(default=Decimal("0.0"), ge=0)

    realized_pnl: Decimal = Field(default=Decimal("0.0"))
    unrealized_pnl: Decimal = Field(default=Decimal("0.0"))

    # Associated tracking
    strategy_id: str | None = None
    entry_signal_id: UUID | None = None

    # Current active stops (synchronized with broker)
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None

    created_at: datetime
    updated_at: datetime


class PortfolioSnapshot(BaseModel):
    """
    Authoritative snapshot of an account's financial state.
    """

    model_config = ConfigDict(from_attributes=True)

    account_id: str
    timestamp: datetime

    cash: Decimal = Field(..., description="Total cash balance")
    available_cash: Decimal = Field(..., description="Cash not locked in open orders/margin")

    equity: Decimal = Field(..., description="Total account equity (cash + unrealized PnL)")

    total_realized_pnl: Decimal = Field(default=Decimal("0.0"))
    total_unrealized_pnl: Decimal = Field(default=Decimal("0.0"))

    total_exposure: Decimal = Field(
        default=Decimal("0.0"), description="Total market value of open positions"
    )
    reserved_capital: Decimal = Field(
        default=Decimal("0.0"), description="Capital reserved for risk limits"
    )
