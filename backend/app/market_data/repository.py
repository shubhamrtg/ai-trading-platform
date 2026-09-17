import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_data import CandleModel

logger = logging.getLogger(__name__)


class CandleRepository:
    """Repository for persisting and querying historical market data."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_candles(
        self, symbol: str, timeframe: str, start_time: datetime, end_time: datetime
    ) -> list[CandleModel]:
        """Fetch chronologically ordered candles from the local database cache."""
        stmt = (
            select(CandleModel)
            .where(
                CandleModel.symbol == symbol,
                CandleModel.timeframe == timeframe,
                CandleModel.timestamp >= start_time,
                CandleModel.timestamp <= end_time,
            )
            .order_by(CandleModel.timestamp.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_existing_timestamps(
        self, symbol: str, timeframe: str, start_time: datetime, end_time: datetime
    ) -> set[datetime]:
        """Get a set of timestamps that already exist in the database for the given range."""
        stmt = (
            select(CandleModel.timestamp)
            .where(
                CandleModel.symbol == symbol,
                CandleModel.timeframe == timeframe,
                CandleModel.timestamp >= start_time,
                CandleModel.timestamp <= end_time,
            )
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def is_range_covered(
        self, symbol: str, timeframe: str, start_time: datetime, end_time: datetime
    ) -> bool:
        """Check if the requested range is completely covered by prior fetches."""
        from app.models.market_data import MarketDataCoverageModel
        stmt = select(MarketDataCoverageModel).where(
            MarketDataCoverageModel.symbol == symbol,
            MarketDataCoverageModel.timeframe == timeframe,
            MarketDataCoverageModel.start_time <= start_time,
            MarketDataCoverageModel.end_time >= end_time,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first() is not None

    async def mark_range_covered(
        self, symbol: str, timeframe: str, start_time: datetime, end_time: datetime
    ) -> None:
        """Mark a range as covered after a successful fetch."""
        from app.models.market_data import MarketDataCoverageModel
        coverage = MarketDataCoverageModel(
            symbol=symbol,
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time
        )
        self.session.add(coverage)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()

    async def insert_missing(self, models: list[CandleModel]) -> None:
        """Insert a batch of new candles, ignoring explicit duplicate constraint violations."""
        if not models:
            return

        for model in models:
            self.session.add(model)
            try:
                await self.session.commit()
            except IntegrityError as e:
                await self.session.rollback()
                err_str = str(e.orig).lower() if e.orig else str(e).lower()

                # Check if it specifically represents the expected uniqueness conflict
                # (symbol, timeframe, timestamp). We do not use ON CONFLICT DO UPDATE.
                is_expected = False
                if "unique" in err_str:
                    if "uq_candle_identity" in err_str or ("symbol" in err_str and "timestamp" in err_str):
                        is_expected = True
                elif "duplicate key" in err_str and "uq_candle_identity" in err_str:
                    is_expected = True

                if not is_expected:
                    # Propagate unrelated integrity failures (NOT NULL, etc.)
                    raise e

                logger.debug(f"Ignored expected duplicate insert for {model.symbol} at {model.timestamp}")
