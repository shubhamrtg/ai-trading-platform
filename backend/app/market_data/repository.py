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

    async def insert_missing(self, models: list[CandleModel]) -> None:
        """Insert a batch of new candles.
        
        The caller is expected to filter out existing candles. 
        If a concurrent transaction inserted the same candles, we catch IntegrityError,
        rollback, and assume they exist (protecting reproducibility).
        """
        if not models:
            return

        self.session.add_all(models)

        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            logger.info("IntegrityError during candle insertion. Concurrent fetch likely occurred.")
            # We don't retry here because the cache-first read loop in the service
            # will just pick up the newly inserted rows by the winner transaction.
