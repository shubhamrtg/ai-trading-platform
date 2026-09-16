from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import StrategyStatus
from app.models.strategy import StrategyVersionModel


class StrategyVersionRepository:
    """Repository for retrieving authoritative strategy versions from persistence."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_executable_version(
        self, strategy_id: str, version: str
    ) -> StrategyVersionModel | None:
        """Fetch a strategy version, ensuring it is active/executable."""
        stmt = (
            select(StrategyVersionModel)
            .where(StrategyVersionModel.strategy_id == strategy_id)
            .where(StrategyVersionModel.version == version)
        )
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if record is None:
            return None

        if record.status != StrategyStatus.ACTIVE:
            return None

        return record
