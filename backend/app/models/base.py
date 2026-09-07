"""SQLAlchemy declarative base with common columns for all models.

All database models should inherit from Base to get consistent
primary key, timestamp, and metadata behavior.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models.

    Provides:
    - Auto-incrementing integer primary key
    - created_at timestamp (server-side default)
    - updated_at timestamp (auto-updated on modification)
    """

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
