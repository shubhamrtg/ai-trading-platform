"""Strongly-typed application settings with safety-first defaults.

All configuration is loaded from environment variables and validated
at startup using Pydantic. Invalid or missing critical configuration
causes the application to fail immediately rather than running in an
unsafe state.
"""

from enum import Enum
from typing import Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    """Trading execution mode.

    BACKTEST: Historical data replay, simulated execution. Default and safest.
    PAPER: Live market data, simulated execution. No real money.
    LIVE: Live market data, real broker execution. REQUIRES explicit enablement.
    """

    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


class LogFormat(str, Enum):
    """Log output format."""

    JSON = "json"
    CONSOLE = "console"


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Safety design:
    - Trading mode defaults to BACKTEST (no real money at risk)
    - LIVE mode requires three independent gates to activate
    - Missing or invalid config fails the application at startup
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "AI Trading Platform"
    app_version: str = "0.1.0"
    debug: bool = False

    # --- Trading Mode ---
    trading_mode: TradingMode = TradingMode.BACKTEST

    # --- Live Trading Safety Gates ---
    # All three must be correctly set to enable LIVE mode.
    live_trading_enabled: bool = False
    live_trading_confirmation: str = ""

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://trading:trading_dev_password@localhost:5432/trading_platform",
        description="PostgreSQL connection string (asyncpg driver)",
    )
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_echo: bool = False

    # --- Redis ---
    redis_url: Optional[str] = "redis://localhost:6379/0"

    # --- Logging ---
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.CONSOLE

    # --- Security ---
    secret_key: str = "CHANGE-ME-IN-PRODUCTION-USE-A-REAL-SECRET-KEY"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Ensure log level is a valid Python logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid_levels:
            raise ValueError(f"Invalid log level '{v}'. Must be one of: {valid_levels}")
        return upper

    @model_validator(mode="after")
    def validate_live_trading_gates(self) -> "Settings":
        """Enforce triple-gate safety for LIVE trading mode.

        LIVE mode requires ALL of:
        1. trading_mode == LIVE
        2. live_trading_enabled == True
        3. live_trading_confirmation == exact confirmation string

        If trading_mode is LIVE but the gates are not satisfied,
        the application MUST NOT start.
        """
        if self.trading_mode == TradingMode.LIVE:
            errors: list[str] = []

            if not self.live_trading_enabled:
                errors.append(
                    "LIVE_TRADING_ENABLED must be set to 'true'"
                )

            expected_confirmation = "I_UNDERSTAND_REAL_MONEY_IS_AT_RISK"
            if self.live_trading_confirmation != expected_confirmation:
                errors.append(
                    f"LIVE_TRADING_CONFIRMATION must be set to '{expected_confirmation}'"
                )

            if errors:
                raise ValueError(
                    "LIVE trading mode safety gates not satisfied. "
                    "Live trading CANNOT be enabled until ALL gates pass:\n"
                    + "\n".join(f"  - {e}" for e in errors)
                )

        return self

    @property
    def is_live_trading(self) -> bool:
        """Whether the system is in live trading mode."""
        return self.trading_mode == TradingMode.LIVE

    @property
    def is_paper_trading(self) -> bool:
        """Whether the system is in paper trading mode."""
        return self.trading_mode == TradingMode.PAPER

    @property
    def is_backtesting(self) -> bool:
        """Whether the system is in backtesting mode."""
        return self.trading_mode == TradingMode.BACKTEST
