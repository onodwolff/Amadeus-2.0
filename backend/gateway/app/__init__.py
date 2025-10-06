"""FastAPI application package for the Amadeus gateway."""

from .logging import setup_logging

setup_logging()

__all__ = ["setup_logging"]
