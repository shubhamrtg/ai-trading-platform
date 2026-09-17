"""Database models package.

All SQLAlchemy models must be imported here so that Alembic
can discover them for auto-generating migrations.
"""

from app.models.audit import AuditEventModel
from app.models.base import Base
from app.models.backtesting import BacktestRunModel
from app.models.portfolio import PortfolioSnapshotModel, PositionModel
from app.models.strategy import StrategyModel, StrategyVersionModel
from app.models.trading import (
    AIAssessmentModel,
    FillModel,
    OrderIntentModel,
    OrderModel,
    RiskDecisionModel,
    SignalModel,
)

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
    "BacktestRunModel",
]

from app.models.market_data import CandleModel

__all__.append("CandleModel")

from app.models.market_data import MarketDataCoverageModel
__all__.append('MarketDataCoverageModel')
