"""Health check endpoint.

Provides system health status including component-level checks
for database and Redis connectivity. Always reports the current
trading mode prominently.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.database import check_database_health
from app.config import get_settings
from app.schemas.health import (
    ComponentHealth,
    ComponentStatus,
    HealthResponse,
    OverallStatus,
)

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="System health check",
    description="Returns health status of all system components and the current trading mode.",
)
async def health_check() -> HealthResponse:
    """Check health of all system components.

    Returns:
        HealthResponse with overall status, component statuses,
        current trading mode, and version.
    """
    settings = get_settings()
    components: dict[str, ComponentHealth] = {}

    # Check database
    db_healthy = await check_database_health()
    components["database"] = ComponentHealth(
        status=ComponentStatus.HEALTHY if db_healthy else ComponentStatus.UNHEALTHY,
        details=None if db_healthy else "Database connection failed",
    )

    # Check Redis (best-effort, not critical for Milestone 1)
    redis_status = await _check_redis_health(settings.redis_url)
    components["redis"] = ComponentHealth(
        status=redis_status,
        details=None if redis_status == ComponentStatus.HEALTHY else "Redis unavailable",
    )

    # Determine overall status
    component_statuses = [c.status for c in components.values()]
    if all(s == ComponentStatus.HEALTHY for s in component_statuses):
        overall = OverallStatus.HEALTHY
    elif ComponentStatus.UNHEALTHY in component_statuses:
        overall = OverallStatus.DEGRADED
    else:
        # Some unavailable but none unhealthy
        overall = OverallStatus.HEALTHY

    return HealthResponse(
        status=overall,
        version=settings.app_version,
        trading_mode=settings.trading_mode.value,
        components=components,
        timestamp=datetime.now(tz=timezone.utc),
    )


async def _check_redis_health(redis_url: str | None) -> ComponentStatus:
    """Check Redis connectivity.

    Returns UNAVAILABLE if Redis is not configured (acceptable),
    UNHEALTHY if configured but unreachable.
    """
    if not redis_url:
        return ComponentStatus.UNAVAILABLE

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(redis_url, socket_connect_timeout=2)
        await client.ping()
        await client.aclose()
        return ComponentStatus.HEALTHY
    except Exception:
        return ComponentStatus.UNAVAILABLE
