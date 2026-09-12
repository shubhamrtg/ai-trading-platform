"""FastAPI application entry point.

Creates and configures the application with:
- Lifespan management (database setup/teardown)
- CORS middleware
- Route registration
- Trading mode display in API docs
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import api_router
from app.api.system import reset_start_time
from app.config import get_settings
from app.config.settings import TradingMode
from app.database import close_database, setup_database
from app.logging import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager.

    Startup:
    - Configures structured logging
    - Connects to database
    - Records start time

    Shutdown:
    - Closes database connections
    """
    settings = get_settings()

    # Configure logging
    setup_logging(log_level=settings.log_level, log_format=settings.log_format)

    logger.info(
        "application_starting",
        version=settings.app_version,
        trading_mode=settings.trading_mode.value,
        debug=settings.debug,
    )

    # Safety banner for trading mode
    if settings.trading_mode == TradingMode.LIVE:
        logger.warning(
            "LIVE_TRADING_MODE_ACTIVE",
            message="⚠️  LIVE TRADING IS ENABLED — REAL MONEY IS AT RISK",
        )
    elif settings.trading_mode == TradingMode.PAPER:
        logger.info("paper_trading_mode", message="Paper trading mode — no real money at risk")
    else:
        logger.info("backtest_mode", message="Backtest mode — historical simulation only")

    # Setup database
    setup_database(
        database_url=settings.database_url,
        pool_size=settings.database_pool_size,
        echo=settings.database_echo,
    )

    # Record application start time
    reset_start_time()

    logger.info("application_started")

    yield

    # Shutdown
    logger.info("application_shutting_down")
    await close_database()
    logger.info("application_stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI instance.
    """
    settings = get_settings()

    # Include trading mode in API docs title for visibility
    mode_label = settings.trading_mode.value
    title = f"{settings.app_name} [{mode_label}]"

    app = FastAPI(
        title=title,
        version=__version__,
        description=(
            f"AI-powered automated trading platform. Currently operating in **{mode_label}** mode."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    app.include_router(api_router)

    return app


# Application instance for uvicorn
app = create_app()
