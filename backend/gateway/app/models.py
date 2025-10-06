"""Backwards compatible re-export of ORM models.

The actual SQLAlchemy model definitions now live in ``gateway.db.models``.
"""
from __future__ import annotations

try:  # pragma: no cover - support running from backend/ directory
    from gateway.db.models import *  # type: ignore # noqa: F401,F403
    from gateway.db.models import __all__ as _models_all
except ModuleNotFoundError:  # pragma: no cover - support running from backend/
    from backend.gateway.db.models import *  # type: ignore # noqa: F401,F403
    from backend.gateway.db.models import __all__ as _models_all  # type: ignore

__all__ = list(_models_all)

