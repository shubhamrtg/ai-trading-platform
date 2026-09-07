"""Async database engine and session management.

Uses SQLAlchemy 2.x async engine with asyncpg driver for PostgreSQL.
Provides dependency injection for FastAPI endpoints and a health
check function for monitoring.
"""

from collections.abc import AsyncGenerator
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.logging import get_logger

logger = get_logger(__name__)

# Module-level engine and session factory (initialized in setup_database)
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def setup_database(
    database_url: str,
    pool_size: int = 5,
    echo: bool = False,
) -> AsyncEngine:
    """Create and configure the async database engine.

    Args:
        database_url: PostgreSQL connection string with asyncpg driver.
        pool_size: Connection pool size.
        echo: Whether to log SQL statements.

    Returns:
        The configured async engine.
    """
    global _engine, _session_factory

    _engine = create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=echo,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    logger.info("database_configured", pool_size=pool_size)
    return _engine


def get_engine() -> AsyncEngine:
    """Get the current database engine.

    Raises:
        RuntimeError: If the database has not been set up yet.
    """
    if _engine is None:
        raise RuntimeError("Database not initialized. Call setup_database() first.")
    return _engine


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides an async database session.

    Yields:
        An async SQLAlchemy session that is automatically closed after use.

    Raises:
        RuntimeError: If the database has not been set up yet.
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call setup_database() first.")

    async with _session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def check_database_health() -> bool:
    """Check database connectivity by executing a simple query.

    Returns:
        True if the database is reachable, False otherwise.
    """
    if _engine is None:
        return False

    try:
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("database_health_check_failed", error=str(exc))
        return False


async def close_database() -> None:
    """Dispose of the database engine and release all connections."""
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
        logger.info("database_connections_closed")
        _engine = None
        _session_factory = None
