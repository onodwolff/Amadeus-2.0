"""Centralized application configuration for the gateway service."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_ROOT_DIR = Path(__file__).resolve().parents[3]
_GATEWAY_DIR = _ROOT_DIR / "backend" / "gateway"
_DEFAULT_ENV_FILES: tuple[Path, ...] = (
    _ROOT_DIR / ".env",
    _GATEWAY_DIR / ".env",
)


class EngineSettings(BaseModel):
    """Runtime configuration for Nautilus engine integration."""

    default_mode: Literal["backtest", "sandbox", "live"] = "backtest"
    max_nodes: int = Field(default=8, ge=1)
    bootstrap_timeout_seconds: int = Field(default=30, ge=1)
    log_level: str = Field(default="INFO", description="Structlog log level")


class DataSettings(BaseModel):
    """Market data configuration."""

    provider: str = "mock"
    cache_ttl_seconds: int = Field(default=60, ge=0)
    cache_backend: Literal["memory", "lfu"] = "memory"
    base_path: Path = Field(default=_ROOT_DIR / "data")

    @field_validator("base_path", mode="before")
    @classmethod
    def _normalise_base_path(cls, value: str | Path) -> Path:
        if isinstance(value, Path):
            return value.expanduser().resolve()
        return Path(value).expanduser().resolve()


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
    """Relational and cache storage configuration."""

    database_url: str = Field(
        default="postgresql+asyncpg://amadeus:amadeus@localhost:5432/amadeus",
        validation_alias=AliasChoices("DATABASE_URL", "STORAGE__DATABASE_URL"),
    )
    redis_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REDIS_URL", "STORAGE__REDIS_URL"),
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def _ensure_database_url(cls, value: str | None) -> str:
        """Ensure that a usable database URL is provided."""

        if value is None:
            raise ValueError("DATABASE_URL must be configured")

        url = value.strip()
        if not url:
            raise ValueError("DATABASE_URL must be a non-empty string")
        return url


class SecuritySettings(BaseModel):
    """Security related configuration values."""

    encryption_key_hex: str = Field(
        default="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        validation_alias=AliasChoices("AMAD_ENC_KEY", "SECURITY__ENCRYPTION_KEY"),
        description="32-byte hex encoded key used for encrypting API secrets.",
    )
    use_mock_services: bool = Field(
        default=True,
        validation_alias=AliasChoices("AMAD_USE_MOCK", "SECURITY__USE_MOCK"),
    )

    @field_validator("encryption_key_hex", mode="before")
    @classmethod
    def _validate_key(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("AMAD_ENC_KEY must be provided as a 32-byte hex string")
        value = value.strip()
        try:
            key_bytes = bytes.fromhex(value)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError("AMAD_ENC_KEY must be a valid hex string") from exc
        if len(key_bytes) != 32:
            raise ValueError("AMAD_ENC_KEY must decode to exactly 32 bytes")
        return value

    @property
    def encryption_key_bytes(self) -> bytes:
        return bytes.fromhex(self.encryption_key_hex)


class Settings(BaseSettings):
    """Top level FastAPI gateway configuration."""

    env: str = Field(default="dev", validation_alias=AliasChoices("ENV", "APP_ENV"))
    engine: EngineSettings = Field(default_factory=EngineSettings)
    data: DataSettings = Field(default_factory=DataSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)

    model_config = SettingsConfigDict(
        env_file=_DEFAULT_ENV_FILES,
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        return self.storage.database_url

    @property
    def redis_url(self) -> str | None:
        return self.storage.redis_url

    @property
    def default_engine_mode(self) -> str:
        return self.engine.default_mode

    @property
    def encryption_key(self) -> bytes:
        return self.security.encryption_key_bytes

    @property
    def use_mock_services(self) -> bool:
        return self.security.use_mock_services


settings = Settings()

__all__ = [
    "AuthSettings",
    "DataSettings",
    "EngineSettings",
    "RiskSettings",
    "SecuritySettings",
    "Settings",
    "StorageSettings",
    "settings",
]
