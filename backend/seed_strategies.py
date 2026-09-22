import asyncio
import sys
from datetime import UTC, datetime

# Setup paths for importing app modules
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.database import setup_database, get_engine
from app.config import get_settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# Import Strategy Registry and models
from app.strategies.sdk import StrategyRegistry
from app.models.strategy import StrategyModel, StrategyVersionModel

# Ensure the moving average crossover is registered
import app.strategies.examples.moving_average_crossover

async def main():
    settings = get_settings()
    engine = setup_database(settings.database_url)

    async with AsyncSession(engine) as session:
        # Loop through all strategies in the registry and sync them
        count = 0
        for (strategy_id, version), (strat_class, source_hash) in StrategyRegistry._strategies.items():
            meta = strat_class.metadata
            print(f"Syncing {strategy_id} v{version} (Hash: {source_hash[:8]}...)")

            # Ensure Strategy exists
            stmt = select(StrategyModel).where(StrategyModel.strategy_id == strategy_id)
            res = await session.execute(stmt)
            strat = res.scalar_one_or_none()
            
            if not strat:
                strat = StrategyModel(
                    strategy_id=strategy_id,
                    name=meta.name,
                    description=meta.description,
                    author="System",
                    status="ACTIVE",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC)
                )
                session.add(strat)
                await session.flush()
            else:
                strat.status = "ACTIVE"
            
            # Ensure Version exists
            stmt_v = select(StrategyVersionModel).where(
                StrategyVersionModel.strategy_id == strategy_id,
                StrategyVersionModel.version == version
            )
            res_v = await session.execute(stmt_v)
            strat_v = res_v.scalar_one_or_none()

            if not strat_v:
                strat_v = StrategyVersionModel(
                    strategy_id=strategy_id,
                    version=version,
                    status="ACTIVE",
                    source_hash=source_hash,
                    supported_asset_classes=list(meta.supported_asset_classes),
                    supported_timeframes=list(meta.supported_timeframes),
                    required_indicators=list(meta.required_indicators),
                    parameters_schema=strat_class.parameters_schema.model_json_schema() if strat_class.parameters_schema else {},
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC)
                )
                session.add(strat_v)
                count += 1
            else:
                strat_v.status = "ACTIVE"

        await session.commit()
        print(f"Successfully synced {count} new strategy versions to the database.")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
