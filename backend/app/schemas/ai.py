"""Pydantic schema for AI advisory assessments.

AI output is strictly advisory. It has NO authority to:
- Place orders
- Bypass the Risk Engine
- Create OrderIntents
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AIRecommendation


class AIAssessment(BaseModel):
    """Structured output from the AI Advisory layer evaluating a Signal."""

    model_config = ConfigDict(from_attributes=True)

    assessment_id: UUID = Field(..., description="Unique ID for this assessment")
    correlation_id: UUID = Field(..., description="Links to the originating trading decision")
    signal_id: UUID = Field(..., description="The signal being assessed")

    provider: str = Field(..., description="AI provider (e.g., 'gemini', 'openai', 'mock')")
    model: str = Field(..., description="Specific model used (e.g., 'gemini-1.5-pro')")

    input_context_hash: str = Field(
        ..., description="Hash of the prompt/context for reproducibility"
    )

    recommendation: AIRecommendation = Field(..., description="ALLOW, REJECT, or HOLD")
    confidence: float = Field(..., ge=0.0, le=1.0, description="AI confidence score (0-1)")
    rationale: str = Field(..., description="Structured explanation of the recommendation")

    timestamp: datetime = Field(..., description="UTC time of the assessment")
