"""Pydantic schema for Risk Engine decisions.

The Risk Engine has FINAL AUTHORITY over all trading decisions.
A RiskDecision must clearly explain why a trade was approved, modified,
or rejected — for audit and compliance purposes.

Cross-field invariants enforced by model_validator:
- REJECTED decisions must NOT have a calculated_quantity.
- APPROVED/MODIFIED decisions must NOT have a rejection_code.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import RiskDecisionStatus


class RiskDecision(BaseModel):
    """Structured output from the deterministic Risk Engine."""

    model_config = ConfigDict(from_attributes=True)

    decision_id: UUID = Field(..., description="Unique ID for this risk decision")
    correlation_id: UUID = Field(..., description="Links to the originating trading decision")
    signal_id: UUID = Field(..., description="The signal being evaluated")

    status: RiskDecisionStatus = Field(..., description="APPROVED, REJECTED, or MODIFIED")

    # If REJECTED, why?
    rejection_code: str | None = Field(
        None,
        description="Standardized rejection code (e.g., 'INSUFFICIENT_FUNDS')",
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

    @model_validator(mode="after")
    def validate_decision_consistency(self) -> "RiskDecision":
        """Enforce cross-field invariants between status and detail fields."""
        if self.status == RiskDecisionStatus.REJECTED:
            if self.calculated_quantity is not None:
                raise ValueError("REJECTED decisions must not have a calculated_quantity")
        else:
            # APPROVED or MODIFIED
            if self.rejection_code is not None:
                raise ValueError("APPROVED/MODIFIED decisions must not have a rejection_code")
        return self
