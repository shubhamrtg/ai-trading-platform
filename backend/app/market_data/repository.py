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

    @staticmethod
    def _compute_fingerprint(timestamps: list[datetime]) -> str:
        """Create a deterministic fingerprint based on the canonical ordered timestamps."""
        import hashlib
        from datetime import UTC
        # Normalize to UTC and sort to ensure deterministic hashing
        normalized = sorted([ts.astimezone(UTC).isoformat() for ts in timestamps])
        hasher = hashlib.sha256()
        for ts_str in normalized:
            hasher.update(ts_str.encode("utf-8"))
        return hasher.hexdigest()

    async def is_range_covered(
        self, symbol: str, timeframe: str, start_time: datetime, end_time: datetime
    ) -> bool:
        """Check if the requested range is completely covered by a prior successful fetch."""
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

        # Load the authoritative persisted timestamps for the recorded coverage interval
        ts_stmt = select(CandleModel.timestamp).where(
            CandleModel.symbol == symbol,
            CandleModel.timeframe == timeframe,
            CandleModel.timestamp >= record.start_time,
            CandleModel.timestamp <= record.end_time,
        )
        ts_result = await self.session.execute(ts_stmt)
        timestamps = list(ts_result.scalars().all())

        # Calculate actual count
        actual_count = len(timestamps)

        # Calculate timestamp fingerprint
        fingerprint = self._compute_fingerprint(timestamps)

        # Compare with stored coverage metadata
        return actual_count == record.actual_count and fingerprint == record.timestamp_fingerprint

    async def mark_range_covered(
        self, symbol: str, timeframe: str, start_time: datetime, end_time: datetime
    ) -> None:
        """Mark a range as covered after a successful fetch, storing the authoritative timestamp fingerprint."""
        from app.models.market_data import MarketDataCoverageModel

        # Read the authoritative persisted candles for the coverage range
        ts_stmt = select(CandleModel.timestamp).where(
            CandleModel.symbol == symbol,
            CandleModel.timeframe == timeframe,
            CandleModel.timestamp >= start_time,
            CandleModel.timestamp <= end_time,
        )
        ts_result = await self.session.execute(ts_stmt)
        timestamps = list(ts_result.scalars().all())

        actual_count = len(timestamps)
        fingerprint = self._compute_fingerprint(timestamps)

        coverage = MarketDataCoverageModel(
            symbol=symbol,
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            actual_count=actual_count,
            timestamp_fingerprint=fingerprint,
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
                    if hasattr(e.orig, "sqlstate") and e.orig.sqlstate == "23505":
                        if hasattr(e.orig, "constraint_name") and e.orig.constraint_name == "uq_candle_identity":
                            is_expected = True
                    if hasattr(e.orig, "pgcode") and e.orig.pgcode == "23505":
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
