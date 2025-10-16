"""Centralized application configuration for the gateway service."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

try:  # pragma: no cover - support running from backend/
    from backend.gateway.db.base import apply_schema_to_metadata
except ModuleNotFoundError:  # pragma: no cover - support running from backend/
    from gateway.db.base import apply_schema_to_metadata  # type: ignore


_ROOT_DIR = Path(__file__).resolve().parents[3]
_GATEWAY_DIR = _ROOT_DIR / "backend" / "gateway"
_DEFAULT_ENV_FILES: tuple[Path, ...] = (
    _ROOT_DIR / ".env",
    _GATEWAY_DIR / ".env",
)

_EMAIL_STR_ADAPTER = TypeAdapter(EmailStr)


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

    enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "AUTH_ENABLED",
            "AUTH__ENABLED",
            "SECURITY_OIDC_ENABLED",
        ),
    )
    jwt_secret: str = Field(default="change-me", min_length=8)
    access_token_ttl_seconds: int = Field(default=600, ge=600, le=600)
    refresh_token_ttl_seconds: int = Field(default=1_209_600, ge=604_800, le=2_592_000)
    idp_issuer: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_IDP_ISSUER",
            "AUTH__IDP_ISSUER",
            "SECURITY_OIDC_ISSUER",
        ),
    )
    idp_audience: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_IDP_AUDIENCE",
            "AUTH__IDP_AUDIENCE",
            "SECURITY_OIDC_AUDIENCE",
        ),
        description="Audience expected in IdP issued tokens.",
    )
    idp_jwks_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_IDP_JWKS_URL",
            "AUTH__IDP_JWKS_URL",
            "SECURITY_OIDC_JWKS_URL",
        ),
        description="JWKS endpoint exposed by the identity provider.",
    )
    idp_authorization_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_IDP_AUTHORIZATION_URL",
            "AUTH__IDP_AUTHORIZATION_URL",
            "SECURITY_OIDC_AUTHORIZATION_URL",
        ),
        description="Authorization endpoint exposed by the identity provider.",
    )
    idp_token_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_IDP_TOKEN_URL",
            "AUTH__IDP_TOKEN_URL",
            "SECURITY_OIDC_TOKEN_URL",
        ),
        description="Token endpoint exposed by the identity provider.",
    )
    idp_algorithms: list[str] = Field(
        default_factory=lambda: ["RS256"],
        validation_alias=AliasChoices(
            "AUTH_IDP_ALGORITHMS",
            "AUTH__IDP_ALGORITHMS",
            "SECURITY_OIDC_ALGORITHMS",
        ),
        description="Signing algorithms accepted from the identity provider.",
    )
    idp_cache_ttl_seconds: int = Field(
        default=600,
        ge=60,
        validation_alias=AliasChoices(
            "AUTH_IDP_CACHE_TTL_SECONDS",
            "AUTH__IDP_CACHE_TTL_SECONDS",
            "SECURITY_OIDC_CACHE_TTL_SECONDS",
        ),
        description="Seconds to cache the JWKS response before refreshing.",
    )
    idp_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_IDP_CLIENT_ID",
            "AUTH__IDP_CLIENT_ID",
            "SECURITY_OIDC_CLIENT_ID",
        ),
        description="OAuth client identifier registered with the identity provider.",
    )
    idp_client_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_IDP_CLIENT_SECRET",
            "AUTH__IDP_CLIENT_SECRET",
            "SECURITY_OIDC_CLIENT_SECRET",
        ),
        description="Optional client secret registered with the identity provider.",
    )
    idp_redirect_uri: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_IDP_REDIRECT_URI",
            "AUTH__IDP_REDIRECT_URI",
            "SECURITY_OIDC_REDIRECT_URI",
        ),
        description="Redirect URI registered for the SPA OIDC client.",
    )
    allow_test_tokens: bool = Field(
        default=True,
        validation_alias=AliasChoices("AUTH_ALLOW_TEST_TOKENS", "AUTH__ALLOW_TEST_TOKENS"),
        description="Enable legacy locally signed tokens for test environments.",
    )
    dev_oidc_fallback: bool | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_DEV_OIDC_FALLBACK",
            "AUTH__DEV_OIDC_FALLBACK",
        ),
        description=(
            "Expose deterministic discovery metadata and JWKS when an identity provider "
            "is not configured. When unset the behaviour defaults to being enabled in dev "
            "environments."
        ),
    )
    cookie_secure: bool = Field(
        default=True,
        validation_alias=AliasChoices("AUTH_COOKIE_SECURE", "AUTH__COOKIE_SECURE"),
        description="Mark refresh token cookies as secure (HTTPS only).",
    )
    refresh_cookie_name: str = Field(
        default="refreshToken",
        validation_alias=AliasChoices(
            "AUTH_REFRESH_COOKIE_NAME",
            "AUTH__REFRESH_COOKIE_NAME",
        ),
        description="Cookie name used to persist refresh tokens.",
    )
    public_base_url: str = Field(
        default="http://localhost:8000",
        validation_alias=AliasChoices("AUTH_PUBLIC_BASE_URL", "AUTH__PUBLIC_BASE_URL"),
        description="External URL where password reset and verification endpoints are exposed.",
    )
    password_reset_path: str = Field(
        default="/auth/reset-password",
        validation_alias=AliasChoices("AUTH_PASSWORD_RESET_PATH", "AUTH__PASSWORD_RESET_PATH"),
    )
    email_verification_path: str = Field(
        default="/auth/verify-email",
        validation_alias=AliasChoices("AUTH_EMAIL_VERIFICATION_PATH", "AUTH__EMAIL_VERIFICATION_PATH"),
    )
    password_reset_token_ttl_seconds: int = Field(
        default=3_600,
        ge=300,
        le=86_400,
        validation_alias=AliasChoices(
            "AUTH_PASSWORD_RESET_TOKEN_TTL_SECONDS",
            "AUTH__PASSWORD_RESET_TOKEN_TTL_SECONDS",
        ),
    )
    email_verification_token_ttl_seconds: int = Field(
        default=172_800,
        ge=300,
        le=604_800,
        validation_alias=AliasChoices(
            "AUTH_EMAIL_VERIFICATION_TOKEN_TTL_SECONDS",
            "AUTH__EMAIL_VERIFICATION_TOKEN_TTL_SECONDS",
        ),
    )
    login_rate_limit_attempts: int = Field(
        default=5,
        ge=1,
        validation_alias=AliasChoices(
            "AUTH_LOGIN_RATE_LIMIT_ATTEMPTS",
            "AUTH__LOGIN_RATE_LIMIT_ATTEMPTS",
        ),
    )
    login_rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        validation_alias=AliasChoices(
            "AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS",
            "AUTH__LOGIN_RATE_LIMIT_WINDOW_SECONDS",
        ),
    )
    login_captcha_failure_threshold: int = Field(
        default=3,
        ge=1,
        validation_alias=AliasChoices(
            "AUTH_LOGIN_CAPTCHA_FAILURE_THRESHOLD",
            "AUTH__LOGIN_CAPTCHA_FAILURE_THRESHOLD",
        ),
    )
    login_captcha_failure_ttl_seconds: int = Field(
        default=900,
        ge=60,
        validation_alias=AliasChoices(
            "AUTH_LOGIN_CAPTCHA_FAILURE_TTL_SECONDS",
            "AUTH__LOGIN_CAPTCHA_FAILURE_TTL_SECONDS",
        ),
    )
    login_rate_limit_namespace: str = Field(
        default="auth:bf",
        validation_alias=AliasChoices(
            "AUTH_LOGIN_RATE_LIMIT_NAMESPACE",
            "AUTH__LOGIN_RATE_LIMIT_NAMESPACE",
        ),
    )
    captcha_verification_url: str = Field(
        default="https://www.google.com/recaptcha/api/siteverify",
        validation_alias=AliasChoices(
            "AUTH_CAPTCHA_VERIFICATION_URL",
            "AUTH__CAPTCHA_VERIFICATION_URL",
        ),
    )
    captcha_secret_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_CAPTCHA_SECRET_KEY",
            "AUTH__CAPTCHA_SECRET_KEY",
        ),
    )
    captcha_site_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_CAPTCHA_SITE_KEY",
            "AUTH__CAPTCHA_SITE_KEY",
        ),
    )
    captcha_timeout_seconds: int = Field(
        default=5,
        ge=1,
        validation_alias=AliasChoices(
            "AUTH_CAPTCHA_TIMEOUT_SECONDS",
            "AUTH__CAPTCHA_TIMEOUT_SECONDS",
        ),
    )
    captcha_test_bypass_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_CAPTCHA_TEST_BYPASS_TOKEN",
            "AUTH__CAPTCHA_TEST_BYPASS_TOKEN",
        ),
    )
    admin_email: EmailStr | None = Field(
        default=None,
        validation_alias=AliasChoices("ADMIN_EMAIL", "AUTH__ADMIN_EMAIL"),
    )
    admin_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ADMIN_PASSWORD", "AUTH__ADMIN_PASSWORD"),
    )
    mfa_challenge_token_ttl_seconds: int = Field(
        default=300,
        ge=60,
        le=900,
        validation_alias=AliasChoices(
            "AUTH_MFA_CHALLENGE_TTL_SECONDS",
            "AUTH__MFA_CHALLENGE_TTL_SECONDS",
        ),
    )

    @field_validator("admin_password", mode="before")
    @classmethod
    def _clean_password(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @field_validator("admin_email", mode="before")
    @classmethod
    def _normalise_admin_email(cls, value: str | EmailStr | None) -> EmailStr | None:
        if value is None:
            return None
        normalised = str(value).strip().lower()
        return _EMAIL_STR_ADAPTER.validate_python(normalised)

    @field_validator("public_base_url", mode="before")
    @classmethod
    def _normalise_public_base_url(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("AUTH_PUBLIC_BASE_URL must be provided")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("AUTH_PUBLIC_BASE_URL must be a non-empty string")
        return cleaned.rstrip("/") or cleaned

    @field_validator("password_reset_path", "email_verification_path", mode="before")
    @classmethod
    def _normalise_paths(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Endpoint paths must be provided")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Endpoint paths must be non-empty strings")
        if not cleaned.startswith("/"):
            cleaned = f"/{cleaned}"
        return cleaned

    @field_validator("login_rate_limit_namespace", mode="before")
    @classmethod
    def _normalise_namespace(cls, value: str | None) -> str:
        if value is None:
            return "auth:bf"
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Login rate limit namespace must be a non-empty string")
        return cleaned

    @field_validator(
        "captcha_secret_key",
        "captcha_site_key",
        "captcha_test_bypass_token",
        "idp_client_id",
        "idp_client_secret",
        "idp_redirect_uri",
        mode="before",
    )
    @classmethod
    def _clean_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("captcha_verification_url", mode="before")
    @classmethod
    def _normalise_captcha_url(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("AUTH_CAPTCHA_VERIFICATION_URL must be provided")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("AUTH_CAPTCHA_VERIFICATION_URL must be a non-empty string")
        return cleaned

    @field_validator("idp_token_url", mode="before")
    @classmethod
    def _normalise_optional_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("idp_algorithms", mode="before")
    @classmethod
    def _normalise_algorithms(cls, value: list[str] | str | None) -> list[str]:
        if value is None:
            return ["RS256"]
        if isinstance(value, str):
            candidates = value.replace(",", " ").split()
        else:
            candidates = [str(item) for item in value]
        cleaned: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalised = candidate.strip().upper()
            if not normalised or normalised in seen:
                continue
            seen.add(normalised)
            cleaned.append(normalised)
        if not cleaned:
            raise ValueError("At least one IdP signing algorithm must be provided")
        return cleaned

    @model_validator(mode="after")
    def _auto_enable(self) -> "AuthSettings":
        """Automatically enable auth when administrator credentials are provided."""

        if not self.enabled and self.admin_email:
            self.enabled = True
        return self

    @property
    def uses_identity_provider(self) -> bool:
        """Return ``True`` when IdP based validation is fully configured."""

        return bool(self.idp_jwks_url and self.idp_issuer)

    @property
    def captcha_configured(self) -> bool:
        """Return ``True`` when CAPTCHA verification can be performed."""

        return bool(self.captcha_secret_key)

    @property
    def idp_audiences(self) -> tuple[str, ...]:
        """Normalised list of IdP audiences configured for token validation."""

        if not self.idp_audience:
            return ()
        parts = self.idp_audience.replace(",", " ").split()
        cleaned: list[str] = []
        seen: set[str] = set()
        for part in parts:
            candidate = part.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            cleaned.append(candidate)
        return tuple(cleaned)


class StorageSettings(BaseModel):
    """Relational and cache storage configuration."""

    database_url: str = Field(
        default="postgresql+asyncpg://amadeus:amadeus@localhost:5432/amadeus",
        validation_alias=AliasChoices("DATABASE_URL", "STORAGE__DATABASE_URL"),
    )
    schema_: str = Field(
        default="public",
        alias="schema",
        validation_alias=AliasChoices("DATABASE_SCHEMA", "STORAGE__DATABASE_SCHEMA"),
        serialization_alias="schema",
    )
    redis_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REDIS_URL", "STORAGE__REDIS_URL"),
    )
    sqlalchemy_echo: bool | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SQLALCHEMY_ECHO",
            "DATABASE_ECHO",
            "STORAGE__SQLALCHEMY_ECHO",
        ),
        description=(
            "When set, overrides the default behaviour for SQLAlchemy's echo flag."
        ),
    )

    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())

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

    @field_validator("schema_", mode="before")
    @classmethod
    def _normalise_schema(cls, value: str | None) -> str:
        if value is None:
            return "public"

        schema = value.strip()
        if not schema:
            raise ValueError("DATABASE_SCHEMA must be a non-empty string")

        return schema

    @property
    def schema(self) -> str:
        return self.schema_


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
    def database_schema(self) -> str:
        return self.storage.schema

    @property
    def sqlalchemy_echo(self) -> bool:
        if self.storage.sqlalchemy_echo is not None:
            return self.storage.sqlalchemy_echo
        return self.env == "dev"

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
apply_schema_to_metadata(settings.storage.schema)

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

