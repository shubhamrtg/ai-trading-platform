"""Paper Execution Adapter.

Fetches a live quote for paper trading without side effects.
"""

from decimal import Decimal
from typing import Protocol


class MarketDataQuoteProvider(Protocol):
    """Protocol for fetching live quotes."""

    async def get_live_quote(self, symbol: str) -> Decimal: ...


class PaperExecutionAdapter:
    """Simulation-only paper execution adapter."""

    def __init__(self, quote_provider: MarketDataQuoteProvider, fee_rate: Decimal = Decimal("0.0")):
        self.quote_provider = quote_provider
        self.fee_rate = fee_rate

    async def get_execution_quote(self, symbol: str, quantity: Decimal) -> tuple[Decimal, Decimal]:
        """Obtain a live quote and calculate simulated fees.

        Returns:
            Tuple of (actual_execution_price, actual_execution_fees)
        """
        # Fetch the live quote from the provider
        actual_execution_price = await self.quote_provider.get_live_quote(symbol)

        # Calculate simulated fees based on notional value
        notional = quantity * actual_execution_price
        actual_execution_fees = notional * self.fee_rate

        return actual_execution_price, actual_execution_fees
