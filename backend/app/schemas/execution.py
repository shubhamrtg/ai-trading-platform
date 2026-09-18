from datetime import datetime
from decimal import Decimal
import uuid
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderSide


class ExecutionStatus(str, Enum):
    """Deterministic status for execution outcome."""
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"


class ExecutionResult(BaseModel):
    """The result of an execution attempt against the Execution Engine.
    
    This strictly represents what happened at the execution boundary.
    """
    model_config = ConfigDict(frozen=True)  # Emphasize immutability

    execution_id: uuid.UUID = Field(..., description="Deterministic business identity for this execution")
    order_intent_id: uuid.UUID = Field(..., description="Source OrderIntent identity")
    correlation_id: uuid.UUID = Field(..., description="Lineage traceability")
    
    symbol: str = Field(..., description="Instrument symbol")
    side: OrderSide = Field(..., description="Order side")
    quantity_requested: Decimal = Field(..., description="Quantity originally requested")
    quantity_executed: Decimal = Field(..., description="Quantity successfully filled")
    
    status: ExecutionStatus = Field(..., description="Outcome status")
    timestamp: datetime = Field(..., description="Authoritative execution timestamp")
    
    trading_mode: str | None = Field(..., description="Authoritative trading mode from the decision")
    
    adapter_identity: str = Field(..., description="Identity of the adapter that performed execution")
    rejection_reason: str | None = Field(default=None, description="Reason if execution was rejected")
