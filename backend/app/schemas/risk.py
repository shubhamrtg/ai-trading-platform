from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RiskDecisionStatus


class RiskDecision(BaseModel):
    """
    Structured output from the deterministic Risk Engine.
    The Risk Engine has FINAL AUTHORITY over all trading decisions.
    """

    model_config = ConfigDict(from_attributes=True)

    decision_id: UUID = Field(..., description="Unique ID for this risk decision")
    signal_id: UUID = Field(..., description="The signal being evaluated")

    status: RiskDecisionStatus = Field(..., description="APPROVED, REJECTED, or MODIFIED")

    # If REJECTED, why?
    rejection_code: str | None = Field(
        None, description="Standardized rejection code (e.g., 'INSUFFICIENT_FUNDS')"
    )
    rejection_reason: str | None = Field(None, description="Human readable reason")

    # If APPROVED or MODIFIED, the final allowed parameters
    calculated_risk: Decimal | None = Field(
        None, description="Calculated monetary risk if executed"
    )
    calculated_quantity: Decimal | None = Field(
        None, description="Final approved quantity to trade"
    )

    # Which limit was the most restrictive (if modified)
    risk_limit_applied: str | None = Field(None, description="Name of the bounding risk rule")

    timestamp: datetime = Field(..., description="UTC time of the decision")
