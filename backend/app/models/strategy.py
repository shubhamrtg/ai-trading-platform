import uuid
from typing import Any, List

from sqlalchemy import JSON, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class StrategyModel(Base):
    """Database representation of a registered strategy."""
    __tablename__ = "strategies"

    strategy_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=True)
    author: Mapped[str] = mapped_column(String, nullable=True)

    versions: Mapped[List["StrategyVersionModel"]] = relationship(back_populates="strategy", cascade="all, delete-orphan")


class StrategyVersionModel(Base):
    """Specific version of a strategy with its parameter schema."""
    __tablename__ = "strategy_versions"

    strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.strategy_id"), index=True)
    version: Mapped[str] = mapped_column(String, nullable=False)
    
    # JSON arrays
    supported_asset_classes: Mapped[list[str]] = mapped_column(JSON, default=list)
    supported_timeframes: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_indicators: Mapped[list[str]] = mapped_column(JSON, default=list)
    
    # JSON schema of expected parameters
    parameters_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    strategy: Mapped["StrategyModel"] = relationship(back_populates="versions")
