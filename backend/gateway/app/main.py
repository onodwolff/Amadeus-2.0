"""FastAPI application factory for the gateway service."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from gateway.app.logging import setup_logging

from .config import settings
from .routes import admin, auth, users

setup_logging()

try:  # pragma: no cover - support running from backend/
    from gateway.db.base import create_engine, dispose_engine
except ModuleNotFoundError:  # pragma: no cover - support running from backend/
    from backend.gateway.db.base import create_engine, dispose_engine  # type: ignore


@asynccontextmanager
async def _lifespan(app: FastAPI):  # pragma: no cover - exercised via integration tests
    """Initialise and tear down shared application resources."""

    create_engine(settings.database_url, echo=settings.env == "dev")
    try:
        yield
    finally:
        await dispose_engine()


def create_app(*, api_prefix: str | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance.

    Parameters
    ----------
    api_prefix:
        Optional path prefix under which the API routers should be mounted. When
        ``None`` the routers are mounted at the application root. Passing an
        explicit value allows callers to inject their own prefix (for example
        ``"/api"`` in production deployments) without altering tests.
    """

    prefix = "" if api_prefix is None else api_prefix

    app = FastAPI(title="Amadeus Gateway", version="2.0", lifespan=_lifespan)

    if settings.env == "dev":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    router_prefix = prefix.rstrip("/") if prefix else ""

    if router_prefix:
        if not router_prefix.startswith("/"):
            router_prefix = f"/{router_prefix}"
        app.include_router(auth.router, prefix=router_prefix)
        app.include_router(users.router, prefix=router_prefix)
        app.include_router(admin.router, prefix=router_prefix)
    else:
        app.include_router(auth.router)
        app.include_router(users.router)
        app.include_router(admin.router)

    return app


app = create_app(api_prefix="/api")
