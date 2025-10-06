"""Application settings loaded from environment and `.env` files."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EngineSettings(BaseModel):
    """Runtime configuration for the trading engine integration."""

    default_mode: Literal["backtest", "live"] = "backtest"
    max_nodes: int = Field(default=8, ge=1)
    bootstrap_timeout_seconds: int = Field(default=30, ge=1)
    log_level: str = Field(default="INFO", description="Structlog log level")


class DataSettings(BaseModel):
    """Market data configuration."""

    provider: str = "mock"
    cache_ttl_seconds: int = Field(default=60, ge=0)
    cache_backend: Literal["memory", "lfu"] = "memory"


class RiskSettings(BaseModel):
    """Risk engine configuration."""

    enabled: bool = False
    max_daily_loss: float = Field(default=0.0, ge=0.0)
    halt_on_breach: bool = True


class AuthSettings(BaseModel):
    """Authentication and authorization configuration."""

    enabled: bool = False
    jwt_secret: str = Field(default="change-me", min_length=8)
    access_token_ttl_seconds: int = Field(default=900, ge=60)
    refresh_token_ttl_seconds: int = Field(default=86400, ge=300)


class StorageSettings(BaseModel):
    """Storage configuration for relational/stateful components."""

    database_url: str = "sqlite+aiosqlite:///./gateway.db"
    snapshot_dir: Optional[str] = None


class Settings(BaseSettings):
    """Top level application settings."""

    env: str = Field(default="dev", validation_alias=AliasChoices("ENV", "APP_ENV"))
    engine: EngineSettings = Field(default_factory=EngineSettings)
    data: DataSettings = Field(default_factory=DataSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)

    model_config = SettingsConfigDict(
        env_file=(Path(__file__).resolve().parent / ".env"),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )


settings = Settings()
