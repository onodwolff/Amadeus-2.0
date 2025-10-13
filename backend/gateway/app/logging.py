"""Logging configuration helpers for the Amadeus gateway."""
from __future__ import annotations

import importlib
import importlib.util as importlib_util
import json
import logging
import os
import sys
from typing import Any

StructlogModule = Any

_structlog_spec = importlib_util.find_spec("structlog")
if _structlog_spec is not None:
    structlog: StructlogModule = importlib.import_module("structlog")
else:  # pragma: no cover
    structlog = None

# --- Fallback для отсутствия structlog ---
try:
    _contextvars = importlib.import_module("structlog.contextvars")
    _bind_contextvars = _contextvars.bind_contextvars
    _clear_contextvars = _contextvars.clear_contextvars
except Exception:  # pragma: no cover
    def _bind_contextvars(*_: Any, **__: Any) -> None: ...
    def _clear_contextvars() -> None: ...

class _StructlogFallbackLogger:
    __slots__ = ("_logger", "_context")
    def __init__(self, logger: logging.Logger, context: dict[str, Any] | None = None) -> None:
        self._logger = logger
        self._context = dict(context or {})
    def bind(self, **kwargs: Any) -> "_StructlogFallbackLogger":
        nc = self._context.copy(); nc.update(kwargs)
        return _StructlogFallbackLogger(self._logger, nc)
    def unbind(self, *keys: str) -> "_StructlogFallbackLogger":
        nc = self._context.copy()
        for k in keys: nc.pop(k, None)
        return _StructlogFallbackLogger(self._logger, nc)
    def new(self, **kwargs: Any) -> "_StructlogFallbackLogger":
        return _StructlogFallbackLogger(self._logger, kwargs)
    def _serialize(self, event: str, data: dict[str, Any]) -> str:
        payload: dict[str, Any] = {"event": event, **self._context}
        if data: payload.update(data)
        try:
            return json.dumps(payload, default=str, sort_keys=True)
        except Exception:
            return f"{event} | {payload}"
    def _log(self, level: int, event: str, *, exc_info: bool = False, **kwargs: Any) -> None:
        self._logger.log(level, self._serialize(event, kwargs), exc_info=exc_info)
    def debug(self, event: str, **kw: Any) -> None: self._log(logging.DEBUG, event, **kw)
    def info(self, event: str, **kw: Any) -> None: self._log(logging.INFO, event, **kw)
    def warning(self, event: str, **kw: Any) -> None: self._log(logging.WARNING, event, **kw)
    def error(self, event: str, **kw: Any) -> None: self._log(logging.ERROR, event, **kw)
    def critical(self, event: str, **kw: Any) -> None: self._log(logging.CRITICAL, event, **kw)
    def exception(self, event: str, **kw: Any) -> None: self._log(logging.ERROR, event, exc_info=True, **kw)
    def log(self, level: int, event: str, **kw: Any) -> None: self._log(level, event, **kw)

def _resolve_log_level(level: str | int | None) -> int:
    if isinstance(level, int): return level
    if isinstance(level, str): return getattr(logging, level.upper(), logging.INFO)
    return logging.INFO

def setup_logging(*, level: str | int | None = None) -> None:
    env_level = os.getenv("LOG_LEVEL")
    resolved = _resolve_log_level(level or env_level)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=resolved, force=True)
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
        wrapper_class=structlog.make_filtering_bound_logger(resolved),
    )

def get_logger(name: str | None = None) -> Any:
    if structlog is not None:
        return structlog.get_logger(name)
    return _StructlogFallbackLogger(logging.getLogger(name or __name__))

def bind_contextvars(**kwargs: Any) -> None: _bind_contextvars(**kwargs)
def clear_contextvars() -> None: _clear_contextvars()

__all__ = ["bind_contextvars", "clear_contextvars", "get_logger", "setup_logging"]
