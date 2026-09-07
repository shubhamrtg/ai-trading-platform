"""Database models package.

All SQLAlchemy models must be imported here so that Alembic
can discover them for auto-generating migrations.
"""

from app.models.base import Base

from app.models.strategy import StrategyModel, StrategyVersionModel
from app.models.trading import (
    SignalModel,
    AIAssessmentModel,
    RiskDecisionModel,
    OrderIntentModel,
    OrderModel,
    FillModel,
)
from app.models.portfolio import PositionModel, PortfolioSnapshotModel
from app.models.audit import AuditEventModel

__all__ = [
    "Base",
    "StrategyModel",
    "StrategyVersionModel",
    "SignalModel",
    "AIAssessmentModel",
    "RiskDecisionModel",
    "OrderIntentModel",
    "OrderModel",
    "FillModel",
    "PositionModel",
    "PortfolioSnapshotModel",
    "AuditEventModel",
]
