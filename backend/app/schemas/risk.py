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

from app.models.enums import RiskDecisionStatus, RiskRejectionCode


class RiskDecision(BaseModel):
    """Structured output from the deterministic Risk Engine."""

    model_config = ConfigDict(from_attributes=True)

    decision_id: UUID = Field(..., description="Unique ID for this risk decision")
    correlation_id: UUID = Field(..., description="Links to the originating trading decision")
    signal_id: UUID = Field(..., description="The signal being evaluated")

    status: RiskDecisionStatus = Field(..., description="APPROVED, REJECTED, or MODIFIED")

    # If REJECTED, why?
    rejection_codes: list[RiskRejectionCode] = Field(
        default_factory=list,
        description="Standardized rejection codes (e.g., ['INSUFFICIENT_FUNDS'])",
    )
    rejection_reasons: list[str] = Field(
        default_factory=list,
        description="Human readable reasons",
    )

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
            if not self.rejection_codes:
                raise ValueError("REJECTED decisions must have at least one rejection_code")
        else:
            # APPROVED or MODIFIED
            if self.rejection_codes:
                raise ValueError("APPROVED/MODIFIED decisions must not have rejection_codes")
        return self


class RiskPolicy(BaseModel):
    """Immutable risk policy configuration."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(..., description="Version of the policy")
    max_order_quantity: Decimal = Field(..., ge=0)
    max_position_quantity: Decimal = Field(..., ge=0)
    max_exposure_amount: Decimal = Field(..., ge=0)
    max_exposure_percent: Decimal = Field(..., ge=0, le=1.0)
    max_risk_per_trade: Decimal = Field(..., ge=0)
    max_daily_loss: Decimal = Field(..., ge=0)
    max_drawdown_percent: Decimal = Field(..., ge=0, le=1.0)
    trading_halted: bool = Field(default=False)


class RiskContext(BaseModel):
    """Immutable state context for evaluating a single signal."""

    model_config = ConfigDict(frozen=True)

    portfolio_equity: Decimal = Field(..., gt=0)
    available_cash: Decimal = Field(..., ge=0)
    current_position: Decimal
    current_exposure: Decimal = Field(..., ge=0)
    daily_pnl: Decimal
    peak_equity: Decimal = Field(..., gt=0)
    current_equity: Decimal = Field(..., gt=0)
    trading_halted: bool = Field(default=False)
    evaluated_at: datetime
