class MarketDataError(Exception):
    """Base exception for market data errors."""
    pass

class ProviderUnavailableError(MarketDataError):
    """Raised when the external historical data provider is unreachable or returns an error."""
    pass

class DataIntegrityError(MarketDataError):
    """Raised when the fetched market data is malformed or invalid."""
    pass

class ChronologyError(DataIntegrityError):
    """Raised when candles are not chronologically ordered."""
    pass
