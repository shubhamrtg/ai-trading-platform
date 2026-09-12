"""Pydantic schemas for health and system status endpoints."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ComponentStatus(str, Enum):
    """Health status for an individual component."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNAVAILABLE = "unavailable"


class OverallStatus(str, Enum):
    """Overall system health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth(BaseModel):
    """Health status of a single component."""

    status: ComponentStatus
    details: str | None = None


class HealthResponse(BaseModel):
    """Response schema for the /health endpoint."""

    status: OverallStatus
    version: str
    trading_mode: str
    components: dict[str, ComponentHealth]
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(tz=datetime.now().astimezone().tzinfo)
    )


class SystemStatusResponse(BaseModel):
    """Response schema for the /api/v1/system/status endpoint."""

    app_name: str
    version: str
    trading_mode: str
    debug: bool
    uptime_seconds: float
    configuration_valid: bool
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(tz=datetime.now().astimezone().tzinfo)
    )
