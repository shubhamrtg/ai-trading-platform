from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderSide, OrderState, OrderType, TimeInForce


class OrderIntent(BaseModel):
    """
    An approved, actionable intent to place an order.
    Created ONLY after Risk Engine approval. Accepted by Execution.
    """

    model_config = ConfigDict(from_attributes=True)

    intent_id: UUID = Field(..., description="Unique ID for this intent")
    originating_signal_id: UUID = Field(..., description="Source signal")
    risk_decision_id: UUID = Field(..., description="Risk decision that authorized this")

    account_id: str = Field(..., description="Target account/portfolio ID")
    symbol: str = Field(..., description="Instrument symbol")

    side: OrderSide = Field(...)
    order_type: OrderType = Field(...)
    quantity: Decimal = Field(..., gt=0)

    limit_price: Decimal | None = Field(None, description="Required if LIMIT or STOP_LIMIT")
    stop_price: Decimal | None = Field(None, description="Required if STOP_MARKET or STOP_LIMIT")

    # Attached orders (OCO / bracket logic)
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None

    time_in_force: TimeInForce = Field(default=TimeInForce.GTC)

    idempotency_key: str = Field(..., description="Strict key to prevent duplicate execution")
    creation_timestamp: datetime = Field(..., description="UTC time created")


class Order(BaseModel):
    """
    The actual order state tracked by the broker/execution engine.
    """

    model_config = ConfigDict(from_attributes=True)

    order_id: UUID = Field(..., description="Internal tracking ID")
    intent_id: UUID = Field(..., description="Link to the OrderIntent")
    broker_order_id: str | None = Field(None, description="ID returned by the broker")

    state: OrderState = Field(...)

    filled_quantity: Decimal = Field(default=Decimal("0.0"), ge=0)
    average_fill_price: Decimal | None = Field(None)

    created_at: datetime
    updated_at: datetime


class Fill(BaseModel):
    """
    A single execution fill against an order.
    """

    model_config = ConfigDict(from_attributes=True)

    fill_id: UUID
    order_id: UUID
    broker_fill_id: str | None = None

    timestamp: datetime
    price: Decimal = Field(..., gt=0)
    quantity: Decimal = Field(..., gt=0)

    fee: Decimal = Field(default=Decimal("0.0"), ge=0)
    fee_asset: str | None = None

    slippage: Decimal | None = Field(None, description="Calculated slippage from expected price")
