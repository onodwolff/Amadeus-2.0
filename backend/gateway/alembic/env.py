"""Alembic environment configuration for the gateway service."""
from __future__ import annotations

import asyncio
import sys
import types
from importlib import metadata as importlib_metadata
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

for path in (REPO_ROOT, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.append(str(path))


def _install_logging_stub() -> None:
    stub = types.ModuleType("gateway.app.logging")
    stub.setup_logging = lambda *_, **__: None  # type: ignore[attr-defined]
    stub.bind_contextvars = lambda **__: None  # type: ignore[attr-defined]
    stub.clear_contextvars = lambda: None  # type: ignore[attr-defined]
    stub.get_logger = lambda *_: None  # type: ignore[attr-defined]
    sys.modules.setdefault("gateway.app.logging", stub)
    sys.modules.setdefault("backend.gateway.app.logging", stub)


_install_logging_stub()


def _install_email_validator_stub() -> None:
    try:
        importlib_metadata.version("email-validator")
        return
    except importlib_metadata.PackageNotFoundError:
        pass

    module = types.ModuleType("email_validator")
    module.__all__ = ["validate_email", "EmailNotValidError"]
    module.__version__ = "2.0.0"

    class EmailNotValidError(ValueError):
        """Fallback error raised when email validation fails."""

    def validate_email(value: str, *args, **kwargs):  # type: ignore[unused-arg]
        return types.SimpleNamespace(email=value)

    module.EmailNotValidError = EmailNotValidError  # type: ignore[attr-defined]
    module.validate_email = validate_email  # type: ignore[attr-defined]
    sys.modules.setdefault("email_validator", module)

    if not getattr(importlib_metadata, "_email_validator_stub_installed", False):
        original_version = importlib_metadata.version

        def _version(package_name: str) -> str:
            if package_name == "email-validator":
                return module.__version__
            return original_version(package_name)

        importlib_metadata.version = _version  # type: ignore[assignment]
        importlib_metadata._email_validator_stub_installed = True  # type: ignore[attr-defined]


_install_email_validator_stub()

from gateway.config import settings
from gateway.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
SCHEMA = settings.storage.schema
VERSION_TABLE = "alembic_version"


def _get_database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    return settings.database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""

    configure_kwargs: dict[str, object] = {
        "url": _get_database_url(),
        "target_metadata": target_metadata,
        "literal_binds": True,
        "dialect_opts": {"paramstyle": "named"},
        "compare_type": True,
        "compare_server_default": True,
        "version_table": VERSION_TABLE,
    }

    if SCHEMA:
        configure_kwargs["version_table_schema"] = SCHEMA
        configure_kwargs["include_schemas"] = True

    context.configure(**configure_kwargs)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    url = _get_database_url()
    connectable: AsyncEngine = create_async_engine(url, poolclass=pool.NullPool)

    async def _run_async_migrations() -> None:
        async with connectable.connect() as connection:
            await connection.run_sync(_run_sync_migrations)
        await connectable.dispose()

    asyncio.run(_run_async_migrations())


def _run_sync_migrations(sync_conn) -> None:
    escaped_schema = None

    if SCHEMA:
        escaped_schema = SCHEMA.replace('"', '""')
        sync_conn.exec_driver_sql(
            f'CREATE SCHEMA IF NOT EXISTS "{escaped_schema}"'
        )
        sync_conn.exec_driver_sql(f'SET search_path TO "{escaped_schema}"')

    configure_kwargs: dict[str, object] = {
        "connection": sync_conn,
        "target_metadata": target_metadata,
        "compare_type": True,
        "compare_server_default": True,
        "version_table": VERSION_TABLE,
    }

    if SCHEMA:
        configure_kwargs["version_table_schema"] = SCHEMA
        configure_kwargs["include_schemas"] = True

    context.configure(**configure_kwargs)

    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
