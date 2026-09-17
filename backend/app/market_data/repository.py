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
        """Check if the requested range is completely covered by a prior successful fetch."""
        from sqlalchemy import func
        from app.models.market_data import MarketDataCoverageModel
        
        # We need a coverage record that completely encloses the requested range
        stmt = select(MarketDataCoverageModel).where(
            MarketDataCoverageModel.symbol == symbol,
            MarketDataCoverageModel.timeframe == timeframe,
            MarketDataCoverageModel.start_time <= start_time,
            MarketDataCoverageModel.end_time >= end_time,
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()
        
        if not record:
            return False
            
        # Verify macroscopic integrity: The exact requested bounds must have preserved all validated candles.
        count_stmt = select(func.count(CandleModel.id)).where(
            CandleModel.symbol == symbol,
            CandleModel.timeframe == timeframe,
            CandleModel.timestamp >= record.start_time,
            CandleModel.timestamp <= record.end_time,
        )
        db_count = await self.session.scalar(count_stmt)
        
        # If the count meets or exceeds expected, the original dataset is fully intact.
        # This prevents falsely reporting coverage if data was manually deleted or the vendor return was truncated.
        return db_count is not None and db_count >= record.expected_count

    async def mark_range_covered(
        self, symbol: str, timeframe: str, start_time: datetime, end_time: datetime, expected_count: int
    ) -> None:
        """Mark a range as covered after a successful fetch, storing the expected candle count."""
        from app.models.market_data import MarketDataCoverageModel
        coverage = MarketDataCoverageModel(
            symbol=symbol,
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            expected_count=expected_count,
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

        dialect_name = self.session.bind.dialect.name if self.session.bind else "unknown"

        for model in models:
            self.session.add(model)
            try:
                await self.session.commit()
            except IntegrityError as e:
                await self.session.rollback()
                
                is_expected = False
                if dialect_name == "postgresql":
                    # For PostgreSQL (asyncpg/psycopg)
                    if hasattr(e.orig, "sqlstate") and getattr(e.orig, "sqlstate") == "23505":
                        if hasattr(e.orig, "constraint_name") and getattr(e.orig, "constraint_name") == "uq_candle_identity":
                            is_expected = True
                    if hasattr(e.orig, "pgcode") and getattr(e.orig, "pgcode") == "23505":
                        if "uq_candle_identity" in str(e.orig):
                            is_expected = True
                    # Fallback for some drivers where it's in the message
                    if "duplicate key value violates unique constraint" in str(e.orig) and "uq_candle_identity" in str(e.orig):
                        is_expected = True
                else:
                    # For SQLite
                    err_str = str(e.orig).lower() if e.orig else str(e).lower()
                    if "unique constraint failed" in err_str:
                        # SQLite explicitly names the columns or constraint
                        if "uq_candle_identity" in err_str or ("symbol" in err_str and "timestamp" in err_str):
                            is_expected = True

                if not is_expected:
                    # Propagate unrelated integrity failures (NOT NULL, foreign key, etc.)
                    raise e

                logger.debug(f"Ignored expected duplicate insert for {model.symbol} at {model.timestamp}")
