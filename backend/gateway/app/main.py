"""FastAPI application factory for the gateway service."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routes import admin, auth, users


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""

    app = FastAPI(title="Amadeus Gateway", version="2.0")

    if settings.env == "dev":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    api_prefix = "/api"

    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(users.router, prefix=api_prefix)
    app.include_router(admin.router, prefix=api_prefix)

    return app


app = create_app()
