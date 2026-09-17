import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import datetime

from app.backtesting.provider import MarketDataProvider
from app.market_data.client import HistoricalVendorClient
from app.market_data.exceptions import ChronologyError, DataIntegrityError
from app.market_data.repository import CandleRepository
from app.models.market_data import CandleModel
from app.schemas.market_data import Candle

logger = logging.getLogger(__name__)


class MarketDataService(MarketDataProvider):
    """Application orchestration service for historical market data.
    
    Provides data to Phase D by prioritizing the local immutable database cache.
    Fetches missing data from the vendor client safely.
    """

    def __init__(self, repository: CandleRepository, vendor_client: HistoricalVendorClient):
        self.repository = repository
        self.vendor_client = vendor_client
        # Optional process-level lock to prevent duplicate concurrent network requests for the same dataset
        self._fetch_locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def get_candles(
        self, symbol: str, timeframe: str, start_time: datetime, end_time: datetime
    ) -> AsyncGenerator[Candle, None]:
        """Implement Phase D MarketDataProvider interface."""

        # 1. Fetch missing data from vendor and populate cache
        await self._ensure_data_cached(symbol, timeframe, start_time, end_time)

        # 2. Stream purely from the authoritative local cache
        db_candles = await self.repository.get_candles(symbol, timeframe, start_time, end_time)

        last_ts = None
        for c in db_candles:
            if c.timestamp.tzinfo is None:
                from datetime import UTC
                c.timestamp = c.timestamp.replace(tzinfo=UTC)

            # Final structural chronology enforcement before yielding to Phase D
            if last_ts and c.timestamp <= last_ts:
                raise ChronologyError(f"Chronology violation in DB cache for {symbol} {timeframe}: {c.timestamp} <= {last_ts}")

            yield Candle.model_validate(c)
            last_ts = c.timestamp

    async def _ensure_data_cached(self, symbol: str, timeframe: str, start_time: datetime, end_time: datetime) -> None:
        """Fetch missing data from the vendor and cache it immutably."""

        # Use an async lock to prevent multiple concurrent requests for the exact same symbol/timeframe
        # doing duplicate network calls within the same process.
        lock_key = (symbol, timeframe)
        if lock_key not in self._fetch_locks:
            self._fetch_locks[lock_key] = asyncio.Lock()

        async with self._fetch_locks[lock_key]:
            # Deterministic coverage logic: Check if the exact requested range is already covered by a prior fetch
            is_covered = await self.repository.is_range_covered(symbol, timeframe, start_time, end_time)
            if is_covered:
                logger.info(f"Cache completely covers requested range for {symbol} between {start_time} and {end_time}. Skipping vendor.")
                return

            # Fetch from vendor
            logger.info(f"Checking vendor data for {symbol} {timeframe} between {start_time} and {end_time}")
            vendor_candles = await self.vendor_client.fetch_historical_candles(symbol, timeframe, start_time, end_time)

            # We still query existing timestamps to enforce the Immutable Cache Contract (never overwrite)
            from datetime import UTC
            raw_timestamps = await self.repository.get_existing_timestamps(symbol, timeframe, start_time, end_time)
            existing_timestamps = {
                ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts
                for ts in raw_timestamps
            }

            if not vendor_candles:
                raise DataIntegrityError(f"Vendor provided insufficient/empty data to establish coverage for {symbol} between {start_time} and {end_time}")

            # Filter and validate
            new_models = []
            last_vendor_ts = None

            for vc in vendor_candles:
                if last_vendor_ts and vc.timestamp <= last_vendor_ts:
                    raise ChronologyError(f"Vendor returned unordered data for {symbol}: {vc.timestamp} <= {last_vendor_ts}")
                last_vendor_ts = vc.timestamp

                # Check range (vendor might over-return)
                if not (start_time <= vc.timestamp <= end_time):
                    continue

                # Skip if already cached (Immutable Cache Rule)
                if vc.timestamp in existing_timestamps:
                    continue

                # Convert to DB model
                new_models.append(CandleModel(
                    symbol=vc.symbol,
                    timeframe=vc.timeframe,
                    timestamp=vc.timestamp,
                    open=vc.open,
                    high=vc.high,
                    low=vc.low,
                    close=vc.close,
                    volume=vc.volume,
                ))

            if new_models:
                logger.info(f"Persisting {len(new_models)} new candles for {symbol}")
                await self.repository.insert_missing(new_models)

            # After a successful fetch and persist, explicitly record that this range is now covered
            # We record the total number of valid candles returned by the vendor to verify macroscopic integrity later.
            await self.repository.mark_range_covered(symbol, timeframe, start_time, end_time, len(vendor_candles))
