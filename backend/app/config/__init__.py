"""Configuration management for the AI Trading Platform.

Uses Pydantic Settings for strongly-typed, validated configuration
loaded from environment variables.
"""

from functools import lru_cache

from app.config.settings import Settings


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings.

    Settings are loaded once from environment variables and cached
    for the lifetime of the application.
    """
    return Settings()


__all__ = ["Settings", "get_settings"]
