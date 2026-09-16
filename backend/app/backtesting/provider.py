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
        """Generate 10 deterministic daily candles for testing."""
        current_time = start_time

        # We'll just generate candles up to end_time or max 10 to keep tests fast
        for i in range(10):
            if current_time > end_time:
                break

            # Intentionally spike the close on the 4th candle for MA crossovers in tests
            close_price = Decimal("110.0") if i == 3 else Decimal("100.0")

            yield Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=current_time,
                open=Decimal("100.0"),
                high=Decimal("110.0"),
                low=Decimal("90.0"),
                close=close_price,
                volume=Decimal("1000.0"),
                vwap=None,
                trades=None,
            )

            # For 1d timeframe
            current_time += timedelta(days=1)
