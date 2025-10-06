"""Logging configuration for the Amadeus gateway."""

from __future__ import annotations

import importlib
import logging
import sys
from typing import Any

from gateway.config import settings

StructlogModule = Any

_structlog_spec = importlib.util.find_spec("structlog")
if _structlog_spec is not None:
    structlog: StructlogModule = importlib.import_module("structlog")
else:  # pragma: no cover - executed only when structlog is missing at runtime
    structlog = None


def _resolve_log_level(level: str | int | None) -> int:
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        return getattr(logging, level.upper(), logging.INFO)
    return logging.INFO


def setup_logging(*, level: str | int | None = None) -> None:
    """Configure structlog to emit JSON logs to stdout."""

    resolved_level = _resolve_log_level(level or settings.engine.log_level)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=resolved_level,
        force=True,
    )

    if structlog is None:
        logging.getLogger(__name__).warning(
            "structlog is not installed; falling back to standard logging output."
        )
        return

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=processors,
        context_class=dict,
        cache_logger_on_first_use=True,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        wrapper_class=structlog.make_filtering_bound_logger(resolved_level),
    )
