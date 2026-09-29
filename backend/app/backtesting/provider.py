from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from decimal import Decimal

from app.schemas.market_data import Candle


class MarketDataProvider(ABC):
    """Abstract interface for historical market data retrieval.

    Provides the required candle stream for Phase D backtesting without
    coupling the engine to a specific storage backend.
    """

    @abstractmethod
    async def get_candles(
        self, symbol: str, timeframe: str, start_time: datetime, end_time: datetime
    ) -> AsyncGenerator[Candle, None]:
        """Yield historical candles chronologically."""
        yield  # type: ignore[misc]


class DummyMarketDataProvider(MarketDataProvider):
    """Deterministic dummy data provider for Phase E tests and local verification.

    Generates deterministic candles on-the-fly.
    """

    async def get_candles(
        self, symbol: str, timeframe: str, start_time: datetime, end_time: datetime
    ) -> AsyncGenerator[Candle, None]:
        """Generate deterministic candles for the requested date range."""
        current_time = start_time

        # Determine timedelta based on timeframe string (basic support)
        if timeframe == "1h":
            delta = timedelta(hours=1)
        elif timeframe == "1m":
            delta = timedelta(minutes=1)
        else:
            delta = timedelta(days=1) # default to 1d

        i = 0
        while current_time <= end_time and i < 10000: # cap at 10,000 to prevent runaway loops
            # Provide some simulated wave pattern for prices so MAs actually cross over
            import math
            wave = Decimal(math.sin(i / 5.0) * 10)

            yield Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=current_time,
                open=Decimal("100.0") + wave,
                high=Decimal("110.0") + wave,
                low=Decimal("90.0") + wave,
                close=Decimal("105.0") + wave,
                volume=Decimal("1000.0"),
                vwap=None,
                trades=None,
            )

            current_time += delta
            i += 1
