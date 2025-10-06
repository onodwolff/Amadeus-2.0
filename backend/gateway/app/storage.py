"""Database and cache integration helpers for the gateway service."""
from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Optional, Awaitable, Any

try:  # pragma: no cover - optional dependency
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    SQLALCHEMY_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    AsyncEngine = AsyncSession = create_async_engine = sessionmaker = None  # type: ignore[assignment]
    SQLALCHEMY_AVAILABLE = False

if SQLALCHEMY_AVAILABLE:
    try:  # pragma: no cover - support running from backend/
        from gateway.db.base import Base
    except ModuleNotFoundError:  # pragma: no cover - support running from backend/
        from backend.gateway.db.base import Base  # type: ignore
else:  # pragma: no cover - fallback when SQLAlchemy missing
    Base = object  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency
    import redis.asyncio as redis
except Exception:  # pragma: no cover - optional dependency
    redis = None


LOGGER = logging.getLogger("gateway.storage")


class DatabaseNotAvailable(RuntimeError):
    """Raised when the configured database cannot be reached."""


@dataclass(slots=True)
class DatabaseConfig:
    """Light-weight configuration container for the async database."""

    url: str
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: float = 30.0


class AsyncDatabase:
    """Async SQLAlchemy helper that hides engine/session boilerplate."""

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[Callable[[], AsyncSession]] = None
        self._lock = asyncio.Lock()
        if not SQLALCHEMY_AVAILABLE:
            raise DatabaseNotAvailable("SQLAlchemy is not installed")

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:  # pragma: no cover - lazy initialisation
            raise DatabaseNotAvailable("Database engine has not been initialised")
        return self._engine

    async def _ensure_engine(self) -> AsyncEngine:
        if self._engine is not None:
            return self._engine

        async with self._lock:
            if self._engine is not None:
                return self._engine

            if create_async_engine is None:
                raise DatabaseNotAvailable("SQLAlchemy async engine unavailable")

            LOGGER.debug("initialising async engine", url=self._config.url)
            engine = create_async_engine(
                self._config.url,
                echo=self._config.echo,
                pool_size=self._config.pool_size,
                max_overflow=self._config.max_overflow,
                pool_timeout=self._config.pool_timeout,
                future=True,
            )
            self._engine = engine
            if sessionmaker is None or AsyncSession is None:
                raise DatabaseNotAvailable("SQLAlchemy sessionmaker unavailable")
            self._session_factory = sessionmaker(
                engine,
                expire_on_commit=False,
                class_=AsyncSession,
            )
        return self._engine

    async def create_all(self) -> None:
        """Create database schema using the configured Base metadata."""

        engine = await self._ensure_engine()
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Provide an ``async with`` ready session context manager."""

        engine = await self._ensure_engine()
        if self._session_factory is None:  # pragma: no cover - defensive
            raise DatabaseNotAvailable("Session factory missing despite engine initialised")

        session: AsyncSession = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


class CacheBackend:
    """Minimal cache interface used by the gateway."""

    async def get(self, key: str) -> Optional[bytes]:  # pragma: no cover - interface
        raise NotImplementedError

    async def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def delete(self, key: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class MemoryCache(CacheBackend):
    """Simple in-memory cache used when Redis isn't configured."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[bytes, Optional[float]]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[bytes]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at is not None and expires_at < asyncio.get_running_loop().time():
                self._store.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> None:
        async with self._lock:
            expires_at = None
            if ttl:
                expires_at = asyncio.get_running_loop().time() + ttl
            self._store[key] = (value, expires_at)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)


class RedisCache(CacheBackend):
    """Redis backed cache using ``redis.asyncio`` if available."""

    def __init__(self, url: str) -> None:
        if redis is None:  # pragma: no cover - optional dependency
            raise RuntimeError("redis.asyncio is not installed")
        self._client = redis.from_url(url)

    async def get(self, key: str) -> Optional[bytes]:
        return await self._client.get(key)

    async def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> None:
        await self._client.set(name=key, value=value, ex=ttl)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)


class CacheFacade:
    """Threaded helper exposing synchronous cache operations."""

    def __init__(self, backend: CacheBackend | None = None) -> None:
        self._backend = backend or MemoryCache()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop_runner, name="gateway-cache", daemon=True)
        self._thread.start()

    def _loop_runner(self) -> None:  # pragma: no cover - infrastructure helper
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def close(self) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _run(self, operation: Awaitable[Any]) -> Any:
        try:
            return asyncio.run_coroutine_threadsafe(operation, self._loop).result(timeout=5.0)
        except Exception:  # pragma: no cover - defensive logging
            LOGGER.warning("cache operation failed", exc_info=True)
            return None

    def get(self, key: str) -> Optional[bytes]:
        return self._run(self._backend.get(key))

    def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> None:
        self._run(self._backend.set(key, value, ttl))

    def delete(self, key: str) -> None:
        self._run(self._backend.delete(key))


def build_cache(redis_url: str | None) -> CacheBackend:
    if redis_url:
        try:
            return RedisCache(redis_url)
        except Exception:  # pragma: no cover - fallback when redis unavailable
            LOGGER.warning("redis cache initialisation failed", exc_info=True)
    return MemoryCache()


__all__ = [
    "AsyncDatabase",
    "Base",
    "CacheBackend",
    "CacheFacade",
    "build_cache",
    "DatabaseConfig",
    "DatabaseNotAvailable",
    "MemoryCache",
    "RedisCache",
]
