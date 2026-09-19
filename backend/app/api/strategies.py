"""Read-only Strategy API endpoints.

Provides listing and detail views for strategies and their versions.
These endpoints are strictly read-only and contain no business logic.
Added in Phase J to support the MVP Web UI.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.strategy import StrategyModel, StrategyVersionModel
from app.schemas.api_strategies import (
    StrategyDetailResponse,
    StrategyListResponse,
    StrategyVersionResponse,
)

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


@router.get("", response_model=list[StrategyListResponse])
async def list_strategies(
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> list[StrategyListResponse]:
    """List all registered strategies with version counts."""
    # Subquery for version counts
    version_count_subq = (
        select(
            StrategyVersionModel.strategy_id,
            func.count().label("version_count"),
        )
        .group_by(StrategyVersionModel.strategy_id)
        .subquery()
    )

    stmt = select(StrategyModel, version_count_subq.c.version_count).outerjoin(
        version_count_subq,
        StrategyModel.strategy_id == version_count_subq.c.strategy_id,
    )

    result = await session.execute(stmt)
    rows = result.all()

    return [
        StrategyListResponse(
            id=strategy.id,
            strategy_id=strategy.strategy_id,
            name=strategy.name,
            description=strategy.description,
            author=strategy.author,
            status=strategy.status,
            version_count=version_count or 0,
        )
        for strategy, version_count in rows
    ]


@router.get("/{strategy_id}", response_model=StrategyDetailResponse)
async def get_strategy(
    strategy_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> StrategyDetailResponse:
    """Get a strategy with all its versions."""
    stmt = (
        select(StrategyModel)
        .where(StrategyModel.strategy_id == strategy_id)
        .options(selectinload(StrategyModel.versions))
    )

    result = await session.execute(stmt)
    strategy = result.scalar_one_or_none()

    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    versions = [
        StrategyVersionResponse(
            id=v.id,
            version=v.version,
            status=v.status,
            source_hash=v.source_hash,
            supported_asset_classes=v.supported_asset_classes,
            supported_timeframes=v.supported_timeframes,
            required_indicators=v.required_indicators,
            parameters_schema=v.parameters_schema,
            created_at=v.created_at.isoformat() if v.created_at else None,
            updated_at=v.updated_at.isoformat() if v.updated_at else None,
        )
        for v in strategy.versions
    ]

    return StrategyDetailResponse(
        id=strategy.id,
        strategy_id=strategy.strategy_id,
        name=strategy.name,
        description=strategy.description,
        author=strategy.author,
        status=strategy.status,
        versions=versions,
    )
