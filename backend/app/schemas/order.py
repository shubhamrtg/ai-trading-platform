"""Pydantic schemas for OrderIntent, Order, and Fill.

Separation of concerns:
- OrderIntent: Risk-approved request (requires risk_decision_id).
- Order: Actual order tracked by the execution engine / broker.
- Fill: Individual execution fill (one Order can have many Fills).

Cross-field invariants enforced by model_validator on OrderIntent:
- LIMIT orders require a limit_price.
- STOP_MARKET orders require a stop_price.
- STOP_LIMIT orders require both limit_price and stop_price.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import OrderSide, OrderState, OrderType, TimeInForce


class OrderIntent(BaseModel):
    """An approved, actionable intent to place an order.

    Created ONLY after Risk Engine approval. Accepted by Execution.
    Cannot be considered executable without a valid risk_decision_id.
    """

    model_config = ConfigDict(from_attributes=True)

    intent_id: UUID = Field(..., description="Unique ID for this intent")
    correlation_id: UUID = Field(..., description="Links to the originating trading decision")
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

    @model_validator(mode="after")
    def validate_price_requirements(self) -> "OrderIntent":
        """Enforce that order types requiring prices have them."""
        if self.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and self.limit_price is None:
            raise ValueError(f"{self.order_type.value} orders require a limit_price")
        if (
            self.order_type in (OrderType.STOP_MARKET, OrderType.STOP_LIMIT)
            and self.stop_price is None
        ):
            raise ValueError(f"{self.order_type.value} orders require a stop_price")
        return self


class Order(BaseModel):
    """The actual order state tracked by the broker/execution engine.

    Self-contained for operational queries — key fields are present
    without needing to JOIN to order_intents.
    """

    model_config = ConfigDict(from_attributes=True)

    order_id: UUID = Field(..., description="Internal tracking ID")
    correlation_id: UUID = Field(..., description="Links to the originating trading decision")
    intent_id: UUID = Field(..., description="Link to the OrderIntent")
    broker_order_id: str | None = Field(None, description="ID returned by the broker")

    # Denormalized from OrderIntent
    symbol: str = Field(..., description="Instrument symbol")
    side: OrderSide = Field(...)
    order_type: OrderType = Field(...)
    quantity: Decimal = Field(..., gt=0)

    state: OrderState = Field(...)

    filled_quantity: Decimal = Field(default=Decimal("0.0"), ge=0)
    average_fill_price: Decimal | None = Field(None)
    rejection_reason: str | None = Field(None)

    created_at: datetime
    updated_at: datetime


class Fill(BaseModel):
    """A single execution fill against an order.

    ONE ORDER ≠ ONE FILL. A broker may partially fill an order multiple times.
    """

    model_config = ConfigDict(from_attributes=True)

    fill_id: UUID
    correlation_id: UUID = Field(..., description="Links to the originating trading decision")
    order_id: UUID
    broker_fill_id: str | None = None

    timestamp: datetime
    price: Decimal = Field(..., gt=0)
    quantity: Decimal = Field(..., gt=0)

    fee: Decimal = Field(default=Decimal("0.0"), ge=0)
    fee_asset: str | None = None

    slippage: Decimal | None = Field(None, description="Calculated slippage from expected price")
