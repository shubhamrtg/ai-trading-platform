from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrategyParameterDefinition(BaseModel):
    """Schema defining a single strategy parameter."""
    name: str
    type: str  # e.g., "int", "float", "str", "bool"
    default: Any
    description: Optional[str] = None
    required: bool = True
    # Validation rules could go here (min, max, options)


class StrategyMetadata(BaseModel):
    """Metadata describing a strategy package."""
    strategy_id: str = Field(..., description="Unique string identifier for the strategy")
    name: str = Field(..., description="Human readable name")
    version: str = Field(..., description="Semantic version, e.g., '1.2.0'")
    author: Optional[str] = None
    description: Optional[str] = None
    
    supported_asset_classes: List[str] = Field(default_factory=list)
    supported_timeframes: List[str] = Field(default_factory=list)
    required_indicators: List[str] = Field(default_factory=list)
    
    parameters: List[StrategyParameterDefinition] = Field(default_factory=list)


class StrategyConfig(BaseModel):
    """Specific configuration/parameters used for a strategy run/backtest."""
    model_config = ConfigDict(from_attributes=True)
    
    config_id: UUID
    strategy_id: str
    version: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


class StrategyRunContext(BaseModel):
    """
    Context passed to a strategy during execution.
    Contains necessary references without allowing direct trading access.
    """
    run_id: UUID
    mode: str  # BACKTEST, PAPER, LIVE
    config: StrategyConfig
