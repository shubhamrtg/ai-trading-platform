"""Strategy and StrategyVersion persistence models.

StrategyModel: Represents a registered trading strategy.
StrategyVersionModel: Represents a specific immutable version of a strategy.

Design decisions:
- strategy_id is a human-readable string identifier (not auto-incremented).
- Version uniqueness is enforced at the database level via UniqueConstraint.
- source_hash allows verifying that a version's code hasn't been tampered with.
- Status tracks the lifecycle (DRAFT → ACTIVE → DEPRECATED → DISABLED).
- Executable strategy logic lives in the Strategy SDK, NOT in these models.
"""

from typing import Any

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import StrategyStatus


class StrategyModel(Base):
    """Database representation of a registered strategy."""

    __tablename__ = "strategies"

    strategy_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[StrategyStatus] = mapped_column(
        String, nullable=False, default=StrategyStatus.DRAFT
    )

    versions: Mapped[list["StrategyVersionModel"]] = relationship(
        back_populates="strategy", cascade="all, delete-orphan"
    )


class StrategyVersionModel(Base):
    """Immutable version record for a specific strategy.

    Once created, the version string and parameters_schema should not change.
    Use status to deprecate/disable instead of modifying.

    The (strategy_id, version) pair is enforced unique at the database level
    to prevent duplicate version registration.
    """

    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_id", "version", name="uq_strategy_version"),)

    strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.strategy_id"), index=True)
    version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[StrategyStatus] = mapped_column(
        String, nullable=False, default=StrategyStatus.DRAFT
    )

    # Optional hash of strategy source for integrity verification
    source_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    # JSON arrays describing capabilities
    supported_asset_classes: Mapped[list[str]] = mapped_column(JSON, default=list)
    supported_timeframes: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_indicators: Mapped[list[str]] = mapped_column(JSON, default=list)

    # JSON schema of expected parameters (frozen snapshot)
    parameters_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    strategy: Mapped["StrategyModel"] = relationship(back_populates="versions")
