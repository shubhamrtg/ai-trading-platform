from typing import Any

from app.strategies.repository import StrategyVersionRepository
from app.strategies.runner import StrategyRunner, StrategyValidationError


class StrategyExecutionService:
    """Service to safely instantiate strategy runners from authoritative persisted versions."""

    def __init__(self, repository: StrategyVersionRepository):
        self._repository = repository

    async def create_runner(
        self,
        strategy_id: str,
        version: str,
        parameters_dict: dict[str, Any]
    ) -> StrategyRunner:
        """Create a StrategyRunner by explicitly resolving the persisted StrategyVersion."""

        # 1. Load persisted StrategyVersion from repository
        version_record = await self._repository.get_executable_version(strategy_id, version)
        if not version_record:
            raise StrategyValidationError(
                f"Persisted executable StrategyVersion '{strategy_id}' v'{version}' not found."
            )

        # 2. Authoritative instantiation
        return StrategyRunner(version_record, parameters_dict)
