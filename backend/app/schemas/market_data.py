from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class Candle(BaseModel):
    """
    Canonical representation of a market candlestick/bar.
    All prices and volumes are represented as precise decimals.
    """

    model_config = ConfigDict(from_attributes=True)

    symbol: str = Field(..., description="The trading instrument symbol, e.g., 'BTC-USD'")
    timestamp: datetime = Field(..., description="The exact start time of the candle in UTC")
    timeframe: str = Field(..., description="The timeframe identifier, e.g., '1m', '1h', '1d'")

    open: Decimal = Field(..., description="Opening price")
    high: Decimal = Field(..., description="Highest price during the period")
    low: Decimal = Field(..., description="Lowest price during the period")
    close: Decimal = Field(..., description="Closing price")
    volume: Decimal = Field(..., ge=0, description="Trading volume during the period")

    # Optional fields for deeper analysis
    vwap: Decimal | None = Field(None, description="Volume Weighted Average Price if available")
    trades: int | None = Field(None, ge=0, description="Number of individual trades")
