"""Pydantic schemas for Strategy API boundary.

Read-only response schemas for exposing strategy and version information
to the frontend. These contain no business logic.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import StrategyStatus


class StrategyVersionResponse(BaseModel):
    """API response for a single strategy version."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    version: str
    status: StrategyStatus
    source_hash: str | None = None
    supported_asset_classes: list[str] = Field(default_factory=list)
    supported_timeframes: list[str] = Field(default_factory=list)
    required_indicators: list[str] = Field(default_factory=list)
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class StrategyListResponse(BaseModel):
    """API response for a strategy in a list view."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    strategy_id: str
    name: str
    description: str | None = None
    author: str | None = None
    status: StrategyStatus
    version_count: int = 0


class StrategyDetailResponse(BaseModel):
    """API response for a strategy with all its versions."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    strategy_id: str
    name: str
    description: str | None = None
    author: str | None = None
    status: StrategyStatus
    versions: list[StrategyVersionResponse] = Field(default_factory=list)
