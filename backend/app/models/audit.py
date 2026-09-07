import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import String, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditEventModel(Base):
    """
    Append-only audit log for tracing every trading decision.
    """
    __tablename__ = "audit_events"

    event_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    
    correlation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    component: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    
    trading_mode: Mapped[str] = mapped_column(String, index=True)
    
    # Context references
    strategy_id: Mapped[str | None] = mapped_column(String, nullable=True)
    symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    signal_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
