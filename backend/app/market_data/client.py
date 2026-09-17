import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from app.market_data.exceptions import ChronologyError, DataIntegrityError, ProviderUnavailableError
from app.schemas.market_data import Candle

logger = logging.getLogger(__name__)


class HistoricalVendorClient(ABC):
    """Abstract interface for historical market data vendor clients.
    
    Responsible for fetching and normalizing raw external data into Candle objects.
    """

    @abstractmethod
    async def fetch_historical_candles(
        self, symbol: str, timeframe: str, start_time: datetime, end_time: datetime
    ) -> list[Candle]:
        """Fetch historical candles from the vendor.
        
        Args:
            symbol: Trading pair symbol (e.g., 'AAPL', 'BTC-USD').
            timeframe: Candle interval (e.g., '1d', '1h').
            start_time: Start of the requested range (UTC).
            end_time: End of the requested range (UTC).
            
        Returns:
            Chronological list of parsed Candle objects.
        """
        pass


class YahooFinanceClient(HistoricalVendorClient):
    """Concrete client for Yahoo Finance historical data."""

    # Map internal timeframes to Yahoo's valid intervals
    TIMEFRAME_MAP = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "60m",
        "1d": "1d",
        "1wk": "1wk",
        "1mo": "1mo",
    }

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self.http_client = http_client or httpx.AsyncClient(timeout=10.0)

    async def fetch_historical_candles(
        self, symbol: str, timeframe: str, start_time: datetime, end_time: datetime
    ) -> list[Candle]:
        if timeframe not in self.TIMEFRAME_MAP:
            raise ValueError(f"Unsupported timeframe for Yahoo Finance: {timeframe}")

        interval = self.TIMEFRAME_MAP[timeframe]

        # Yahoo finance expects unix timestamps
        period1 = int(start_time.timestamp())
        period2 = int(end_time.timestamp())

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {
            "period1": period1,
            "period2": period2,
            "interval": interval,
            "events": "history",
        }

        # Yahoo Finance often blocks default user agents
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        try:
            response = await self.http_client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Yahoo returns 404 for missing symbols
                raise DataIntegrityError(f"Symbol {symbol} not found on Yahoo Finance (404)")
            raise ProviderUnavailableError(f"Yahoo Finance returned error: {e.response.status_code}") from e
        except httpx.RequestError as e:
            raise ProviderUnavailableError(f"Failed to connect to Yahoo Finance: {e}") from e

        return self._parse_yahoo_response(symbol, timeframe, data)

    def _parse_yahoo_response(self, symbol: str, timeframe: str, data: dict[str, object]) -> list[Candle]:
        try:
            # We use Any here to bypass strictly typed dictionary accesses since Yahoo responses are heavily nested
            from typing import Any, cast
            data_any = cast("Any", data)
            result = data_any["chart"]["result"]
            if not result:
                raise DataIntegrityError(f"Vendor response 'result' is empty for {symbol}")

            chart_data = result[0]

            if "timestamp" not in chart_data or not chart_data["timestamp"]:
                raise DataIntegrityError(f"Vendor response is missing the timestamp array for {symbol}")

            timestamps = chart_data["timestamp"]
            indicators = chart_data["indicators"]["quote"][0]

            opens = indicators.get("open", [])
            highs = indicators.get("high", [])
            lows = indicators.get("low", [])
            closes = indicators.get("close", [])
            volumes = indicators.get("volume", [])

            candles: list[Candle] = []

            for i, ts in enumerate(timestamps):
                # Reject missing/invalid timestamps
                if ts is None:
                    raise DataIntegrityError(f"Missing timestamp in Yahoo Finance response for {symbol}")

                # Reject null OHLC values
                if opens[i] is None or highs[i] is None or lows[i] is None or closes[i] is None:
                    raise DataIntegrityError(f"Null price value in Yahoo Finance response for {symbol} at {ts}")

                # Check for negative prices or volumes
                if opens[i] < 0 or highs[i] < 0 or lows[i] < 0 or closes[i] < 0:
                    raise DataIntegrityError(f"Negative price in Yahoo Finance response for {symbol} at {ts}")

                candle_time = datetime.fromtimestamp(ts, tz=UTC)

                candle = Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=candle_time,
                    open=Decimal(str(opens[i])),
                    high=Decimal(str(highs[i])),
                    low=Decimal(str(lows[i])),
                    close=Decimal(str(closes[i])),
                    volume=Decimal(str(volumes[i] if volumes[i] is not None else 0.0)),
                    vwap=None,
                    trades=None,
                )

                # Explicit OHLC relationship validation
                if candle.high < candle.low or candle.high < candle.open or candle.high < candle.close or candle.low > candle.open or candle.low > candle.close:
                    raise DataIntegrityError(f"Invalid OHLC relationship for {symbol} at {candle_time}: O={candle.open}, H={candle.high}, L={candle.low}, C={candle.close}")

                # Strict Chronology validation
                if candles:
                    if candle.timestamp <= candles[-1].timestamp:
                        raise ChronologyError(f"Non-chronological or duplicate timestamp from Yahoo Finance: {candle.timestamp} <= {candles[-1].timestamp}")

                candles.append(candle)

            return candles

        except KeyError as e:
            raise DataIntegrityError(f"Unexpected Yahoo Finance response structure: missing {e}") from e
        except Exception as e:
            raise DataIntegrityError(f"Failed to parse Yahoo Finance response: {e}") from e
