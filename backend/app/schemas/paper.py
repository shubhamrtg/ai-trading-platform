"""Pydantic schemas for Paper Trading."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PaperSessionState


class PaperSessionBase(BaseModel):
    """Base fields for a paper session."""
    
    account_id: str
    strategy_id: str
    strategy_version: str
    symbol: str
    timeframe: str


class PaperSessionCreate(PaperSessionBase):
    """Request to create a paper session."""
    pass


class PaperSessionResponse(PaperSessionBase):
    """Response containing a paper session."""
    
    model_config = ConfigDict(from_attributes=True)
    
    session_id: UUID
    state: PaperSessionState
    worker_owner_id: UUID | None = None
    worker_heartbeat: datetime | None = None
    created_at: datetime
    updated_at: datetime


class StateUpdateResponse(BaseModel):
    """Response after updating session state."""
    
    session_id: UUID
    previous_state: PaperSessionState
    new_state: PaperSessionState


class SizingResult(BaseModel):
    """Result of PositionSizer evaluation."""
    
    quantity: Decimal | None = None
    validation_error: str | None = None
    is_valid: bool = Field(init=False)
    
    def __init__(self, **data: Any):
        super().__init__(**data)
        self.is_valid = self.validation_error is None and self.quantity is not None and self.quantity > 0
