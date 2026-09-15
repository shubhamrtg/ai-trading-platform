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

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint, event, inspect
from sqlalchemy.ext.mutable import MutableDict, MutableList
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
    supported_asset_classes: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list
    )
    supported_timeframes: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list
    )
    required_indicators: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list
    )

    # JSON schema of expected parameters (frozen snapshot)
    parameters_schema: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON), default=dict
    )

    strategy: Mapped["StrategyModel"] = relationship(back_populates="versions")


@event.listens_for(StrategyVersionModel, "before_update")
def enforce_strategy_version_immutability(
    mapper: Any, connection: Any, target: StrategyVersionModel
) -> None:
    """Enforce that strategy definitions are immutable once they leave DRAFT status.

    A strategy version represents a specific executable definition. Modifying it after
    it has been activated would break the reproducibility of historical backtests and
    trade logic.
    """
    # Get the state of the object before this update
    state = inspect(target)

    # If it's a new object (not yet in DB), nothing to check here (handled by insert)
    if not state.has_identity:
        return

    # We must look at the ORIGINAL status in the database to determine if it was protected.
    # If the user is currently changing it from DRAFT -> ACTIVE, they are allowed to
    # update fields one last time during that transition.
    status_history = state.attrs.status.history
    original_status = target.status
    if status_history.has_changes():
        if status_history.deleted:
            original_status = status_history.deleted[0]
        else:
            original_status = state.committed_state.get("status", target.status)

    if original_status == StrategyStatus.DRAFT:
        # DRAFT versions can be modified freely.
        return

    # Once a strategy leaves DRAFT, the following fields become immutable
    immutable_fields = [
        "strategy_id",
        "version",
        "source_hash",
        "supported_asset_classes",
        "supported_timeframes",
        "required_indicators",
        "parameters_schema",
    ]

    for field in immutable_fields:
        history = getattr(state.attrs, field).history
        if history.has_changes():
            raise ValueError(
                f"Cannot modify immutable field '{field}' on a StrategyVersion "
                f"that is in {original_status} status."
            )
