"""Utility for applying Alembic migrations with development-friendly defaults."""
from __future__ import annotations

import argparse
import os
import sys
import types
from pathlib import Path

from alembic import command
from alembic.config import Config


REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "backend" / "gateway" / "alembic.ini"


def _install_logging_stub() -> None:
    stub = types.ModuleType("gateway.app.logging")
    stub.setup_logging = lambda *_, **__: None  # type: ignore[attr-defined]
    stub.bind_contextvars = lambda **__: None  # type: ignore[attr-defined]
    stub.clear_contextvars = lambda: None  # type: ignore[attr-defined]
    stub.get_logger = lambda *_: None  # type: ignore[attr-defined]
    sys.modules.setdefault("gateway.app.logging", stub)
    sys.modules.setdefault("backend.gateway.app.logging", stub)


def _patch_sqlite() -> None:
    from sqlalchemy import Enum, text
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"  # type: ignore[attr-defined]

    original_create = Enum.create

    def _enum_create(self, bind, checkfirst=True, **kw):  # type: ignore[override]
        if bind.dialect.name == "sqlite":
            return None
        return original_create(self, bind, checkfirst=checkfirst, **kw)

    Enum.create = _enum_create  # type: ignore[assignment]

    original_text = text

    def _patched_text(source: str, *args, **kwargs):
        if isinstance(source, str) and "::jsonb" in source:
            source = source.replace("::jsonb", "")
        return original_text(source, *args, **kwargs)

    import sqlalchemy

    sqlalchemy.text = _patched_text  # type: ignore[assignment]


def run_migrations(database_url: str) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    _install_logging_stub()
    if database_url.startswith("sqlite"):
        _patch_sqlite()
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "backend" / "gateway" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Alembic migrations")
    parser.add_argument(
        "--database-url",
        dest="database_url",
        default=None,
        help="Database URL to migrate (falls back to DATABASE_URL env var)",
    )
    args = parser.parse_args()

    db_url = args.database_url or os.environ.get("DATABASE_URL")
    if not db_url:
        parser.error("DATABASE_URL must be provided via flag or environment variable")

    run_migrations(db_url)


if __name__ == "__main__":
    main()
