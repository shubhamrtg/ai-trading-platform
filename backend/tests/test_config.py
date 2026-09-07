"""Tests for configuration management and trading mode safety gates."""

import os

import pytest

from app.config.settings import Settings, TradingMode


class TestDefaultConfiguration:
    """Test that default configuration is safe."""

    def test_default_mode_is_backtest(self):
        """Trading mode MUST default to BACKTEST."""
        settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
        assert settings.trading_mode == TradingMode.BACKTEST

    def test_default_live_trading_disabled(self):
        """Live trading MUST be disabled by default."""
        settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
        assert settings.live_trading_enabled is False

    def test_default_is_not_live(self):
        """System must not report as live trading by default."""
        settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
        assert settings.is_live_trading is False
        assert settings.is_backtesting is True

    def test_paper_mode_sets_correctly(self):
        """PAPER mode should work without live trading gates."""
        settings = Settings(
            trading_mode=TradingMode.PAPER,
            database_url="sqlite+aiosqlite:///:memory:",
        )
        assert settings.trading_mode == TradingMode.PAPER
        assert settings.is_paper_trading is True
        assert settings.is_live_trading is False


class TestLiveTradingSafetyGates:
    """Test triple-gate safety mechanism for LIVE mode."""

    def test_live_mode_requires_all_gates(self):
        """LIVE mode must fail if not all gates are satisfied."""
        with pytest.raises(ValueError, match="safety gates not satisfied"):
            Settings(
                trading_mode=TradingMode.LIVE,
                database_url="sqlite+aiosqlite:///:memory:",
            )

    def test_live_mode_fails_without_enabled_flag(self):
        """LIVE mode must fail if only confirmation is set."""
        with pytest.raises(ValueError, match="LIVE_TRADING_ENABLED"):
            Settings(
                trading_mode=TradingMode.LIVE,
                live_trading_enabled=False,
                live_trading_confirmation="I_UNDERSTAND_REAL_MONEY_IS_AT_RISK",
                database_url="sqlite+aiosqlite:///:memory:",
            )

    def test_live_mode_fails_without_confirmation(self):
        """LIVE mode must fail if only enabled flag is set."""
        with pytest.raises(ValueError, match="LIVE_TRADING_CONFIRMATION"):
            Settings(
                trading_mode=TradingMode.LIVE,
                live_trading_enabled=True,
                live_trading_confirmation="",
                database_url="sqlite+aiosqlite:///:memory:",
            )

    def test_live_mode_fails_with_wrong_confirmation(self):
        """LIVE mode must fail if confirmation string is incorrect."""
        with pytest.raises(ValueError, match="LIVE_TRADING_CONFIRMATION"):
            Settings(
                trading_mode=TradingMode.LIVE,
                live_trading_enabled=True,
                live_trading_confirmation="yes_i_want_live_trading",
                database_url="sqlite+aiosqlite:///:memory:",
            )

    def test_live_mode_succeeds_with_all_gates(self):
        """LIVE mode should only work when ALL three gates pass."""
        settings = Settings(
            trading_mode=TradingMode.LIVE,
            live_trading_enabled=True,
            live_trading_confirmation="I_UNDERSTAND_REAL_MONEY_IS_AT_RISK",
            database_url="sqlite+aiosqlite:///:memory:",
        )
        assert settings.trading_mode == TradingMode.LIVE
        assert settings.is_live_trading is True


class TestConfigurationValidation:
    """Test configuration validation and error handling."""

    def test_invalid_log_level_fails(self):
        """Invalid log levels should be rejected."""
        with pytest.raises(ValueError, match="Invalid log level"):
            Settings(
                log_level="INVALID",
                database_url="sqlite+aiosqlite:///:memory:",
            )

    def test_valid_log_levels_accepted(self):
        """All standard log levels should be accepted."""
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            settings = Settings(
                log_level=level,
                database_url="sqlite+aiosqlite:///:memory:",
            )
            assert settings.log_level == level

    def test_log_level_case_insensitive(self):
        """Log level should accept any case."""
        settings = Settings(
            log_level="debug",
            database_url="sqlite+aiosqlite:///:memory:",
        )
        assert settings.log_level == "DEBUG"

    def test_pool_size_minimum(self):
        """Pool size must be at least 1."""
        with pytest.raises(ValueError):
            Settings(
                database_pool_size=0,
                database_url="sqlite+aiosqlite:///:memory:",
            )

    def test_pool_size_maximum(self):
        """Pool size must not exceed 50."""
        with pytest.raises(ValueError):
            Settings(
                database_pool_size=100,
                database_url="sqlite+aiosqlite:///:memory:",
            )
