"""System status endpoint.

Provides detailed system information including trading mode,
uptime, version, and configuration validity.
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import get_settings
from app.schemas.health import SystemStatusResponse

router = APIRouter(prefix="/api/v1", tags=["system"])

# Application start time (set when module is first imported)
_start_time: float = time.monotonic()


def reset_start_time() -> None:
    """Reset the application start time. Used during app startup."""
    global _start_time
    _start_time = time.monotonic()


@router.get(
    "/system/status",
    response_model=SystemStatusResponse,
    summary="System status",
    description="Returns detailed system status including trading mode, uptime, and configuration.",
)
async def system_status() -> SystemStatusResponse:
    """Get current system status.

    Returns:
        SystemStatusResponse with app info, trading mode,
        uptime, and configuration status.
    """
    settings = get_settings()
    uptime = time.monotonic() - _start_time

    return SystemStatusResponse(
        app_name=settings.app_name,
        version=settings.app_version,
        trading_mode=settings.trading_mode.value,
        debug=settings.debug,
        uptime_seconds=round(uptime, 2),
        configuration_valid=True,
        timestamp=datetime.now(tz=timezone.utc),
    )
