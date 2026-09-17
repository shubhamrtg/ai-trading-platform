import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.backtesting import BacktestRunModel

logger = logging.getLogger(__name__)


class BacktestRunRepository:
    """Repository for BacktestRun persistence operations."""

    def __init__(self, db_session: AsyncSession):
        self.session = db_session

    async def get_by_id(self, run_id: UUID) -> BacktestRunModel | None:
        """Retrieve a backtest run by its UUID."""
        stmt = select(BacktestRunModel).where(BacktestRunModel.run_id == run_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, key: str) -> BacktestRunModel | None:
        """Retrieve a backtest run by its idempotency key."""
        stmt = select(BacktestRunModel).where(BacktestRunModel.idempotency_key == key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, model: BacktestRunModel) -> BacktestRunModel:
        """Persist a new backtest run.

        If an IntegrityError occurs due to an idempotency-key UNIQUE collision
        (concurrent duplicate request), the transaction is rolled back and the
        existing run is returned.  Non-idempotency IntegrityErrors are re-raised.
        """
        self.session.add(model)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()

            # Only handle the idempotency-key collision path.
            if model.idempotency_key is not None:
                existing = await self.get_by_idempotency_key(model.idempotency_key)
                if existing is not None:
                    logger.info(
                        "Idempotency collision resolved for key=%s, returning existing run_id=%s",
                        model.idempotency_key,
                        existing.run_id,
                    )
                    return existing

            # Not an idempotency collision — propagate the original error.
            raise exc

        await self.session.refresh(model)
        return model

    async def update(self, model: BacktestRunModel) -> BacktestRunModel:
        """Update an existing backtest run."""
        await self.session.commit()
        await self.session.refresh(model)
        return model

    async def list_runs(self, limit: int = 100, offset: int = 0) -> Sequence[BacktestRunModel]:
        """List summary of backtest runs."""
        stmt = (
            select(BacktestRunModel)
            .order_by(BacktestRunModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
