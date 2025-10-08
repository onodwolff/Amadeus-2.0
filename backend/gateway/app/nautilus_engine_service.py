"""Gateway integration helpers for the NautilusTrader engine.

This module centralises the wiring required for the gateway to interact with
an underlying NautilusTrader deployment.  It provides a small event bus used by
the HTTP handlers and WebSocket producers to exchange telemetry without
coupling them to the concrete engine implementation.  When the actual
``nautilus_trader`` package is importable we expose a couple of convenience
helpers for loading configuration and bootstrapping nodes, while keeping the
mock/simulated implementations available for tests.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import inspect
import os
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
import uuid
import threading
from typing import IO, Any, AsyncIterator, Callable, Dict, Iterable, List, Optional, Tuple, Union

try:  # pragma: no cover - optional dependency during unit tests
    import nautilus_trader as nt  # type: ignore
except Exception:  # pragma: no cover - optional dependency during unit tests
    nt = None

try:  # pragma: no cover - optional dependency for async database access
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
except Exception:  # pragma: no cover - optional dependency during unit tests
    AsyncSession = None  # type: ignore[assignment]
    async_sessionmaker = None  # type: ignore[assignment]
    create_async_engine = None  # type: ignore[assignment]
    select = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency for ORM models
    from gateway.db.models import ApiKey
except Exception:  # pragma: no cover - optional dependency during unit tests
    ApiKey = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency for YAML parsing
    import yaml
except Exception:  # pragma: no cover - optional dependency during unit tests
    yaml = None

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .crypto import decrypt


def retrieve_key(key_id: str, key_type: str) -> Optional[str]:
    """Best-effort helper returning a credential for *key_id* and *key_type*."""

    if not key_id:
        return None

    normalised_id = key_id.upper().replace("-", "_").replace(":", "_")
    normalised_type = key_type.upper().replace("-", "_")
    candidates = [
        f"{normalised_id}_{normalised_type}",
        f"{normalised_id}_{key_type.upper()}",
        f"{key_id}_{key_type}".upper(),
        normalised_type,
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        value = os.environ.get(candidate)
        if value:
            return value
    return None


class EngineConfigError(ValueError):
    """Base error for engine configuration handling."""

    def __init__(self, message: str, *, errors: Optional[Iterable[str]] = None) -> None:
        super().__init__(message)
        self.errors = list(errors or [])


class EngineConfigParseError(EngineConfigError):
    """Raised when a configuration document cannot be parsed."""


class EngineConfigValidationError(EngineConfigError):
    """Raised when a configuration document fails schema validation."""


class EngineConfigStorageError(EngineConfigError):
    """Raised when a configuration document cannot be persisted."""


class EngineMode(str, Enum):
    """Supported runtime modes for Nautilus nodes."""

    BACKTEST = "backtest"
    SANDBOX = "sandbox"
    LIVE = "live"


@dataclass(frozen=True)
class EngineNodeLaunch:
    """Payload describing a requested node launch."""

    mode: EngineMode
    detail: str
    config: Dict[str, Any]


@dataclass
class EngineNodeHandle:
    """Handle referencing a Nautilus trading node running in the background."""

    id: str
    mode: EngineMode
    node: Any
    thread: threading.Thread
    user_id: Optional[str]
    started_at: datetime
    config_version: int
    adapters: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        """Return a serialisable snapshot describing the running node."""

        return {
            "id": self.id,
            "mode": self.mode.value,
            "user_id": self.user_id,
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "alive": self.thread.is_alive(),
            "config_version": self.config_version,
        }


@dataclass
class AdapterPlanEntry:
    """Container describing adapter setup for a Nautilus trading node."""

    name: str
    identifier: str
    mode: str
    sandbox: bool
    data_factory: Optional[Any] = None
    exec_factory: Optional[Any] = None
    data_config: Optional[Any] = None
    exec_config: Optional[Any] = None
    detail: Dict[str, Any] = field(default_factory=dict)
    sources: List[str] = field(default_factory=list)


class EngineEventBus:
    """Thread-safe asynchronous pub/sub helper for gateway telemetry."""

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._external_loop = loop
        if loop is None:
            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(
                target=self._loop_runner,
                name="nautilus-gateway-bus",
                daemon=True,
            )
            self._loop_thread.start()
        else:
            self._loop = loop
            self._loop_thread = None

        self._subscriptions: Dict[str, set[asyncio.Queue]] = {}
        self._lock = threading.RLock()

    def _loop_runner(self) -> None:  # pragma: no cover - infrastructure helper
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    @property
    def external(self) -> bool:
        return self._external_loop is not None

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        """Publish *payload* to all subscribers listening on *topic*."""

        with self._lock:
            queues = list(self._subscriptions.get(topic, set()))

        for queue in queues:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None

            if running_loop is self._loop:
                queue.put_nowait(payload)
            elif self._loop.is_running():
                asyncio.run_coroutine_threadsafe(queue.put(payload), self._loop)
            else:  # pragma: no cover - loop bootstrap path
                queue.put_nowait(payload)

    @contextlib.asynccontextmanager
    async def subscribe(self, topic: str) -> AsyncIterator["EngineSubscription"]:
        """Return an asynchronous subscription to *topic*."""

        queue: asyncio.Queue = asyncio.Queue()
        subscription = EngineSubscription(self, topic, queue)

        with self._lock:
            self._subscriptions.setdefault(topic, set()).add(queue)

        try:
            yield subscription
        finally:
            with self._lock:
                queues = self._subscriptions.get(topic)
                if queues is not None:
                    queues.discard(queue)
                    if not queues:
                        self._subscriptions.pop(topic, None)

    async def drain(self) -> None:
        """Stop the internally managed event loop (mainly for tests)."""

        if self._external_loop is not None:
            return

        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread is not None and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=1.0)


class EngineSubscription:
    """Asynchronous iterator returned by :class:`EngineEventBus`."""

    def __init__(
        self,
        bus: EngineEventBus,
        topic: str,
        queue: asyncio.Queue,
    ) -> None:
        self._bus = bus
        self._topic = topic
        self._queue = queue

    def __aiter__(self) -> "EngineSubscription":
        return self

    async def __anext__(self) -> Dict[str, Any]:
        payload = await self._queue.get()
        if payload is None:  # pragma: no cover - defensive guard
            raise StopAsyncIteration
        return payload

    async def get(self) -> Dict[str, Any]:
        """Explicit awaitable helper returning the next payload."""

        return await self.__anext__()

    def queue(self) -> asyncio.Queue:
        return self._queue


class NautilusEngineService:
    """Minimal wrapper around NautilusTrader engine primitives."""

    def __init__(
        self,
        bus: Optional[EngineEventBus] = None,
        storage_root: Optional[Path] = None,
        *,
        database_url: Optional[str] = None,
        encryption_key: Optional[bytes] = None,
    ) -> None:
        self._bus = bus or EngineEventBus()
        self._nt = nt
        self._storage_root = storage_root or self._default_storage_root()
        self._logger = logging.getLogger(__name__)
        self._nodes_running: Dict[str, EngineNodeHandle] = {}
        # ``active_nodes`` is the public alias used by orchestration layers to
        # reference running engine handles.  Keep it backed by the same dict to
        # preserve existing expectations while exposing the clearer name.
        self.active_nodes: Dict[str, EngineNodeHandle] = self._nodes_running
        self._config_versions: Dict[str, int] = {}
        self._database_url = database_url
        self._encryption_key = encryption_key
        self._api_engine = None
        self._api_session_factory = None
        self._node_configs: Dict[str, Dict[str, Any]] = {}
        self._adapter_status: Dict[str, List[Dict[str, Any]]] = {}
        self._telemetry_threads: Dict[str, Tuple[threading.Thread, threading.Event]] = {}

    @property
    def bus(self) -> EngineEventBus:
        return self._bus

    @property
    def nautilus(self):  # type: ignore[override]
        """Return the imported ``nautilus_trader`` module if available."""

        if self._nt is None:
            raise RuntimeError(
                "nautilus_trader is not installed. Install the package in the gateway "
                "environment or provide the vendor bundle."
            )
        return self._nt

    def ensure_package(self) -> bool:
        """Return whether the Nautilus package is available."""

        return self._nt is not None

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        self._bus.publish(topic, payload)

    async def subscribe(self, topic: str) -> AsyncIterator[EngineSubscription]:
        async with self._bus.subscribe(topic) as subscription:
            yield subscription

    @property
    def storage_root(self) -> Path:
        return self._storage_root

    def _default_storage_root(self) -> Path:
        project_root = Path(__file__).resolve().parents[3]
        return project_root / ".gateway"

    def _ensure_node_storage(self, node_id: str) -> Path:
        root = self.storage_root / "nodes" / node_id
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _persist_config_version(
        self,
        *,
        node_id: str,
        mode: EngineMode,
        version: int,
        config: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> None:
        """Persist a snapshot of the node configuration for auditing purposes."""

        node_dir = self._ensure_node_storage(node_id)
        version_dir = node_dir / "configs"
        version_dir.mkdir(parents=True, exist_ok=True)

        metadata: Dict[str, Any] = {
            "node_id": node_id,
            "mode": mode.value,
            "version": version,
            "saved_at": datetime.utcnow().isoformat() + "Z",
        }
        if user_id:
            metadata["user_id"] = user_id

        version_path = version_dir / f"{mode.value}.v{version}.json"
        meta_path = version_dir / f"{mode.value}.v{version}.meta.json"

        try:
            version_path.write_text(
                json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            meta_path.write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        except OSError as exc:  # pragma: no cover - filesystem issues
            self._logger.debug(
                "Unable to persist config version for node %s: %s",
                node_id,
                exc,
            )

    def load_config_document(
        self,
        content: Any,
        *,
        fmt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Parse a configuration document expressed as JSON or YAML."""

        if isinstance(content, dict):
            return deepcopy(content)

        if isinstance(content, (bytes, bytearray)):
            text = content.decode("utf-8")
        else:
            text = str(content)

        guessed_fmt = (fmt or "").strip().lower()
        if not guessed_fmt:
            stripped = text.lstrip()
            guessed_fmt = "json" if stripped.startswith("{") else "yaml"

        if guessed_fmt == "json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:  # pragma: no cover - stdlib behaviour
                raise EngineConfigParseError(
                    "JSON configuration cannot be decoded",
                    errors=[f"{exc.msg} (line {exc.lineno}, column {exc.colno})"],
                ) from exc
        elif guessed_fmt in {"yaml", "yml"}:
            if yaml is None:
                raise EngineConfigParseError(
                    "PyYAML is required to parse YAML configuration documents."
                )
            try:
                payload = yaml.safe_load(text)  # type: ignore[assignment]
            except yaml.YAMLError as exc:  # pragma: no cover - optional dependency
                raise EngineConfigParseError(
                    "YAML configuration cannot be decoded",
                    errors=[str(exc)],
                ) from exc
        else:
            raise EngineConfigParseError(
                f"Unsupported configuration format '{guessed_fmt}'"
            )

        if payload is None:
            payload = {}

        if not isinstance(payload, dict):
            raise EngineConfigParseError(
                "Configuration root must be an object/mapping, got "
                f"{type(payload).__name__}."
            )

        return payload

    def validate_config(
        self,
        config: Dict[str, Any],
        *,
        mode: Optional[EngineMode] = None,
    ) -> Dict[str, Any]:
        """Validate the minimal schema expected by the gateway."""

        errors: list[str] = []

        config_type = config.get("type")
        if not isinstance(config_type, str):
            errors.append(
                "Field 'type' must be a string with value 'backtest' or 'live'."
            )
        else:
            lowered = config_type.lower()
            if lowered not in {member.value for member in EngineMode}:
                errors.append(
                    "Field 'type' must be either 'backtest' or 'live', "
                    f"got '{config_type}'."
                )
            if mode is not None and lowered != mode.value:
                errors.append(
                    f"Configuration type '{config_type}' does not match requested mode "
                    f"'{mode.value}'."
                )

        strategy = config.get("strategy")
        if not isinstance(strategy, dict):
            errors.append("Field 'strategy' must be an object with id/name parameters.")
        else:
            for field in ("id", "name"):
                value = strategy.get(field)
                if not isinstance(value, str) or not value.strip():
                    errors.append(
                        f"Strategy field '{field}' must be a non-empty string."
                    )
            params = strategy.get("parameters", [])
            if params is not None and not isinstance(params, list):
                errors.append("Strategy 'parameters' must be an array if provided.")

        data_sources = config.get("dataSources", [])
        if data_sources is not None and not isinstance(data_sources, list):
            errors.append("Field 'dataSources' must be an array if provided.")
        elif isinstance(data_sources, list):
            for index, source in enumerate(data_sources):
                if not isinstance(source, dict):
                    errors.append(
                        f"Data source #{index + 1} must be an object, got {type(source).__name__}."
                    )
                    continue
                for field in ("id", "type", "mode"):
                    if field not in source:
                        errors.append(
                            f"Data source #{index + 1} missing required field '{field}'."
                        )

        key_refs = config.get("keyReferences", [])
        if key_refs is not None and not isinstance(key_refs, list):
            errors.append("Field 'keyReferences' must be an array if provided.")
        elif isinstance(key_refs, list):
            for index, ref in enumerate(key_refs):
                if not isinstance(ref, dict):
                    errors.append(
                        f"Key reference #{index + 1} must be an object, got {type(ref).__name__}."
                    )
                    continue
                for field in ("alias", "keyId"):
                    value = ref.get(field)
                    if not isinstance(value, str) or not value.strip():
                        errors.append(
                            f"Key reference #{index + 1} field '{field}' must be a non-empty string."
                        )

        constraints = config.get("constraints")
        if constraints is not None and not isinstance(constraints, dict):
            errors.append("Field 'constraints' must be an object if provided.")

        if errors:
            raise EngineConfigValidationError(
                "Configuration document failed validation.", errors=errors
            )

        return deepcopy(config)

    def prepare_config(
        self,
        content: Any,
        *,
        fmt: Optional[str] = None,
        mode: Optional[EngineMode] = None,
    ) -> Dict[str, Any]:
        """Convenience helper parsing and validating configuration content."""

        document = self.load_config_document(content, fmt=fmt)
        return self.validate_config(document, mode=mode)

    def load_config(
        self,
        file: Union[str, os.PathLike[str], os.PathLike[bytes], IO[str], IO[bytes]],
        *,
        mode: Optional[EngineMode] = None,
    ) -> Dict[str, Any]:
        """Load and validate a configuration document from ``file``."""

        fmt: Optional[str] = None
        payload: Any

        if isinstance(file, (str, os.PathLike)):
            path = Path(file)
            fmt = path.suffix.lstrip(".").lower() or None
            try:
                payload = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise EngineConfigError(
                    f"Configuration file '{path}' could not be read.", errors=[str(exc)]
                ) from exc
        else:
            name = getattr(file, "name", None)
            if isinstance(name, str) and name:
                fmt = Path(name).suffix.lstrip(".").lower() or None

            reader = getattr(file, "read", None)
            if not callable(reader):
                raise EngineConfigError("Configuration input is not readable.")

            try:
                payload = reader()
            except Exception as exc:  # pragma: no cover - defensive guard
                raise EngineConfigError(
                    "Configuration stream could not be read.", errors=[str(exc)]
                ) from exc

        document = self.load_config_document(payload, fmt=fmt)
        return self.validate_config(document, mode=mode)

    def launch_trading_node(
        self,
        mode: EngineMode,
        config: Dict[str, Any],
        user_id: Optional[str] = None,
        *,
        node_id: Optional[str] = None,
    ) -> EngineNodeHandle:
        """Instantiate and start a Nautilus :class:`TradingNode` in the background.

        The returned :class:`EngineNodeHandle` exposes metadata about the running
        node, including the owning thread and the config version used for the
        launch.  Callers may store the handle to perform orchestration tasks
        without holding a strong reference to the underlying ``TradingNode``.
        """

        if self._nt is None:
            raise RuntimeError(
                "nautilus_trader package is not available – unable to start engine nodes."
            )

        safe_config = deepcopy(config)
        resolved_node_id = (
            node_id
            or str(safe_config.get("id") or "").strip()
            or f"node-{len(self.active_nodes) + 1}"
        )
        safe_config.setdefault("id", resolved_node_id)

        if resolved_node_id in self.active_nodes:
            raise RuntimeError(f"Node '{resolved_node_id}' is already running")

        self._node_configs[resolved_node_id] = deepcopy(safe_config)

        plan = self._plan_adapters(mode, safe_config, resolved_node_id, user_id=user_id)

        try:
            from nautilus_trader.trading.node import TradingNode  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "nautilus_trader.trading.node.TradingNode could not be imported"
            ) from exc

        trading_config = self._build_trading_config(mode, plan)
        node = TradingNode(config=trading_config)

        status_snapshot = self._build_adapter_status(resolved_node_id, plan)
        if status_snapshot:
            self._adapter_status[resolved_node_id] = status_snapshot

        self._configure_node_logging(node, resolved_node_id, mode)
        self._register_adapter_factories(node, plan, resolved_node_id)

        version = self._config_versions.get(resolved_node_id, 0) + 1
        self._config_versions[resolved_node_id] = version
        self._persist_config_version(
            node_id=resolved_node_id,
            mode=mode,
            version=version,
            config=safe_config,
            user_id=user_id,
        )

        def runner() -> None:
            try:
                node.start()
            except Exception as exc:  # pragma: no cover - defensive guard
                self._logger.exception(
                    "Nautilus node %s terminated unexpectedly: %s",
                    resolved_node_id,
                    exc,
                )

        thread = threading.Thread(
            target=runner,
            name=f"nautilus-node-{resolved_node_id}",
            daemon=True,
        )
        thread.start()

        if status_snapshot:
            self._set_adapter_state(resolved_node_id, "connected")

        handle = EngineNodeHandle(
            id=resolved_node_id,
            mode=mode,
            node=node,
            thread=thread,
            user_id=user_id,
            started_at=datetime.now(tz=timezone.utc),
            config_version=version,
            adapters=deepcopy(self._adapter_status.get(resolved_node_id, [])),
        )

        self.active_nodes[resolved_node_id] = handle

        try:
            self.attach_bus_listeners(node, resolved_node_id)
        except Exception as exc:  # pragma: no cover - best-effort wiring
            self._logger.debug(
                "Failed to attach Nautilus event listeners for node %s: %s",
                resolved_node_id,
                exc,
            )

        self._publish_node_event(
            node_id=resolved_node_id,
            event="started",
            detail="Node launch requested",
        )

        self._start_telemetry(node, resolved_node_id)

        return handle

    def launch_node(
        self,
        config: Dict[str, Any],
        mode: Union[str, EngineMode],
        *,
        user_id: Optional[str] = None,
        node_id: Optional[str] = None,
    ) -> EngineNodeHandle:
        """Validate ``config`` and launch a Nautilus trading node."""

        engine_mode = EngineMode(mode) if not isinstance(mode, EngineMode) else mode
        validated = self.validate_config(config, mode=engine_mode)
        return self.launch_trading_node(
            engine_mode, validated, user_id, node_id=node_id
        )

    def get_node_handle(self, node_id: str) -> Optional[EngineNodeHandle]:
        """Return the active :class:`EngineNodeHandle` for ``node_id`` if running."""

        return self.active_nodes.get(node_id)

    def get_node_config(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Return the last stored configuration for ``node_id`` if available."""

        config = self._node_configs.get(node_id)
        return deepcopy(config) if config is not None else None

    def stop_trading_node(
        self,
        node_id: str,
        *,
        wait: bool = True,
        timeout: float = 10.0,
    ) -> EngineNodeHandle:
        """Stop a running trading node and update internal bookkeeping."""

        handle = self.active_nodes.get(node_id)
        if handle is None:
            raise KeyError(f"Node '{node_id}' is not running")

        self._set_adapter_state(node_id, "stopping")

        node = handle.node
        thread = handle.thread

        if node is not None:
            stop = getattr(node, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception as exc:  # pragma: no cover - defensive guard
                    self._logger.debug(
                        "Nautilus node %s stop request failed: %s", node_id, exc
                    )
            dispose = getattr(node, "dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except Exception as exc:  # pragma: no cover - defensive guard
                    self._logger.debug(
                        "Nautilus node %s dispose request failed: %s", node_id, exc
                    )

        if wait and thread is not None and thread.is_alive():
            try:
                thread.join(timeout)
            except Exception:  # pragma: no cover - best effort join
                pass

        self._stop_telemetry(node_id)

        handle.node = None

        self.active_nodes.pop(node_id, None)

        self._set_adapter_state(node_id, "stopped")
        handle.adapters = deepcopy(self._adapter_status.get(node_id, []))

        self._publish_node_event(
            node_id=node_id,
            event="stopped",
            detail="Node stop requested",
        )

        return handle

    def restart_trading_node(
        self,
        node_id: str,
        *,
        user_id: Optional[str] = None,
    ) -> EngineNodeHandle:
        """Restart a trading node using the last stored configuration."""

        config = self._node_configs.get(node_id)
        if config is None:
            raise KeyError(f"No configuration stored for node '{node_id}'")

        existing = self.active_nodes.get(node_id)
        preserved_user = user_id or (existing.user_id if existing else None)

        if existing is not None:
            try:
                self.stop_trading_node(node_id)
            except Exception as exc:  # pragma: no cover - defensive guard
                self._logger.debug(
                    "Failed to stop node %s prior to restart: %s", node_id, exc
                )

        config_copy = deepcopy(config)
        config_copy.setdefault("id", node_id)

        config_mode = str(
            config_copy.get("type") or config_copy.get("mode") or ""
        ).lower()
        try:
            engine_mode = EngineMode(config_mode)
        except ValueError:
            engine_mode = existing.mode if existing is not None else EngineMode.LIVE

        return self.launch_trading_node(
            engine_mode,
            config_copy,
            preserved_user,
            node_id=node_id,
        )

    def attach_bus_listeners(self, node: Any, node_id: str) -> None:
        """Bridge Nautilus event callbacks to the gateway event bus."""

        dispatcher = getattr(node, "event_dispatcher", None)
        subscribe = getattr(dispatcher, "subscribe", None) if dispatcher else None
        subscribe_all = (
            getattr(dispatcher, "subscribe_all", None) if dispatcher else None
        )

        kernel = getattr(node, "kernel", None)
        msgbus = getattr(kernel, "msgbus", None) if kernel is not None else None
        msgbus_subscribe = getattr(msgbus, "subscribe", None)

        if not callable(subscribe) and not callable(subscribe_all) and not callable(
            msgbus_subscribe
        ):
            self._logger.debug(
                "Node %s exposes no event dispatcher or message bus – skipping bus bridge.",
                node_id,
            )
            return

        def emit_positions_snapshot() -> None:
            portfolio = getattr(node, "portfolio", None)
            if portfolio is None:
                return
            positions_source = getattr(portfolio, "positions", None)
            try:
                positions = (
                    positions_source()
                    if callable(positions_source)
                    else positions_source
                )
            except Exception:
                return
            if not positions:
                return
            payload: Dict[str, Any] = {
                "event": "snapshot",
                "node_id": node_id,
                "positions": self._serialise_positions(positions),
            }
            self.publish("engine.portfolio", payload)

        def maybe_snapshot_positions(event: Any) -> None:
            event_name = getattr(event, "__class__", type(event)).__name__.lower()
            if any(
                keyword in event_name for keyword in ("fill", "position", "portfolio")
            ):
                emit_positions_snapshot()

        def publish_event(topic: str, field: str, event: Any) -> None:
            event_name = getattr(event, "__class__", type(event)).__name__
            serialised = self._serialise_event(event)
            payload: Dict[str, Any] = {
                "event": event_name,
                "node_id": node_id,
            }
            if topic == "engine.risk.alerts":
                payload[field] = self._build_risk_alert(event, node_id, serialised)
            else:
                payload[field] = (
                    serialised
                    if isinstance(serialised, dict)
                    else {"repr": repr(serialised)}
                )
            self.publish(topic, payload)

        def handle_order(event: Any) -> None:
            publish_event("engine.orders", "order", event)
            maybe_snapshot_positions(event)

        def handle_execution(event: Any) -> None:
            publish_event("engine.executions", "execution", event)
            maybe_snapshot_positions(event)

        def handle_risk(event: Any) -> None:
            publish_event("engine.risk.alerts", "alert", event)

        def handle_generic(event: Any) -> None:
            topic, field = self._map_event_to_topic(
                getattr(event, "__class__", type(event)).__name__
            )
            publish_event(topic, field, event)
            maybe_snapshot_positions(event)

        event_handlers: list[tuple[Any, Callable[[Any], None]]] = []
        order_event = self._resolve_nt_type("model", "events", "order", "OrderEvent")
        order_filled = self._resolve_nt_type("model", "events", "order", "OrderFilled")
        risk_limit = self._resolve_nt_type("risk", "events", "RiskLimitEvent")
        margin_call = self._resolve_nt_type("risk", "events", "MarginCallEvent")

        if order_event is not None:
            event_handlers.append((order_event, handle_order))
        if order_filled is not None:
            event_handlers.append((order_filled, handle_execution))
        if risk_limit is not None:
            event_handlers.append((risk_limit, handle_risk))
        if margin_call is not None and margin_call is not risk_limit:
            event_handlers.append((margin_call, handle_risk))

        subscribed_specific = False
        if callable(subscribe):
            for event_cls, handler in event_handlers:
                if event_cls is None:
                    continue
                try:
                    subscribe(event_cls, handler)
                    subscribed_specific = True
                except TypeError:
                    try:
                        subscribe(event_cls, callback=handler)  # type: ignore[arg-type]
                        subscribed_specific = True
                    except Exception as exc:  # pragma: no cover - optional API shapes
                        self._logger.debug(
                            "Unable to subscribe to %s for node %s: %s",
                            getattr(event_cls, "__name__", str(event_cls)),
                            node_id,
                            exc,
                        )
                except Exception as exc:  # pragma: no cover - optional API shapes
                    self._logger.debug(
                        "Unable to subscribe to %s for node %s: %s",
                        getattr(event_cls, "__name__", str(event_cls)),
                        node_id,
                        exc,
                    )

        if not subscribed_specific and callable(subscribe_all):
            try:
                subscribe_all(handle_generic)
            except TypeError:
                try:
                    subscribe_all(callback=handle_generic)
                except Exception as exc:  # pragma: no cover - optional API shapes
                    self._logger.debug(
                        "Unable to subscribe to Nautilus events for node %s: %s",
                        node_id,
                        exc,
                    )
            except Exception as exc:  # pragma: no cover - optional API shapes
                self._logger.debug(
                    "Unable to subscribe to Nautilus events for node %s: %s",
                    node_id,
                    exc,
                )

        if callable(msgbus_subscribe):
            patterns = {
                "events.order*": handle_order,
                "events.execution*": handle_execution,
                "events.position*": handle_generic,
                "events.risk*": handle_risk,
                "events.*": handle_generic,
            }
            for pattern, handler in patterns.items():
                try:
                    msgbus_subscribe(pattern, handler)
                except Exception:  # pragma: no cover - optional API shapes
                    continue

        def lifecycle_stopped(*_: Any) -> None:
            self._set_adapter_state(node_id, "stopped")
            payload = {
                "event": "stopped",
                "node_id": node_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
            self.publish("engine.nodes", payload)
            self.publish(f"engine.nodes.{node_id}.lifecycle", payload)

        for attribute in ("add_stop_listener", "register_stop_handler", "on_stop"):
            hook = getattr(node, attribute, None)
            if not callable(hook):
                continue
            try:
                hook(lifecycle_stopped)
                break
            except Exception:  # pragma: no cover - optional API shapes
                continue

    def _publish_node_event(self, *, node_id: str, event: str, detail: str) -> None:
        payload = {
            "event": event,
            "node_id": node_id,
            "detail": detail,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self.publish("engine.nodes", payload)
        self.publish(f"engine.nodes.{node_id}.lifecycle", payload)

    def _start_telemetry(self, node: Any, node_id: str) -> None:
        if node is None:
            return
        if node_id in self._telemetry_threads:
            return

        stop_event = threading.Event()

        def runner() -> None:
            while not stop_event.wait(1.0):
                try:
                    sample = self._collect_node_metrics(node, node_id)
                except Exception:  # pragma: no cover - defensive guard
                    continue
                if not sample:
                    continue
                self.publish(f"engine.nodes.{node_id}.metrics", sample)
                self.publish("engine.nodes.metrics", sample)

        thread = threading.Thread(
            target=runner,
            name=f"nautilus-node-{node_id}-telemetry",
            daemon=True,
        )
        self._telemetry_threads[node_id] = (thread, stop_event)
        thread.start()

    def _stop_telemetry(self, node_id: str) -> None:
        entry = self._telemetry_threads.pop(node_id, None)
        if not entry:
            return
        thread, stop_event = entry
        stop_event.set()
        if thread.is_alive():
            try:
                thread.join(timeout=2.0)
            except Exception:  # pragma: no cover - defensive guard
                pass

    def _collect_node_metrics(self, node: Any, node_id: str) -> Optional[Dict[str, Any]]:
        portfolio = getattr(node, "portfolio", None)
        if portfolio is None:
            kernel = getattr(node, "kernel", None)
            portfolio = getattr(kernel, "portfolio", None)
        if portfolio is None:
            return None

        metrics: Dict[str, Optional[float]] = {
            "pnl": None,
            "equity": None,
            "latency_ms": None,
            "cpu_percent": None,
            "memory_mb": None,
        }

        analyzer = getattr(portfolio, "analyzer", None)
        if analyzer is not None:
            try:
                pnl_value = analyzer.total_pnl()  # type: ignore[attr-defined]
            except Exception:
                pnl_value = None
            if pnl_value is not None:
                metrics["pnl"] = self._coerce_number(pnl_value)

            balances = getattr(analyzer, "_account_balances", None)
            if isinstance(balances, dict):
                equity_total = 0.0
                found_equity = False
                for value in balances.values():
                    numeric = self._coerce_money(value)
                    if numeric is None:
                        continue
                    found_equity = True
                    equity_total += numeric
                if found_equity:
                    metrics["equity"] = equity_total

        if not any(value is not None for value in metrics.values()):
            return None

        payload = {
            "node_id": node_id,
            "metrics": {key: value for key, value in metrics.items() if value is not None},
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        return payload

    @staticmethod
    def _coerce_number(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value)
        except Exception:
            return None

    def _coerce_money(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        as_double = getattr(value, "as_double", None)
        if callable(as_double):
            try:
                return float(as_double())
            except Exception:
                pass
        as_decimal = getattr(value, "as_decimal", None)
        if callable(as_decimal):
            try:
                decimal_value = as_decimal()
                return float(decimal_value)
            except Exception:
                pass
        return None

    def submit_order(self, instructions: Dict[str, Any]) -> None:
        """Forward order instructions to a running Nautilus trading node if available."""

        if not self.active_nodes:
            self._logger.debug("No Nautilus nodes active – skipping order submission.")
            return

        target_id = instructions.get("node_id")
        candidates: Iterable[Tuple[str, EngineNodeHandle]]
        if isinstance(target_id, str) and target_id in self.active_nodes:
            candidates = [(target_id, self.active_nodes[target_id])]
        else:
            candidates = list(self.active_nodes.items())

        payload = {
            key: value for key, value in instructions.items() if key != "node_id"
        }

        for node_key, entry in candidates:
            node_obj = entry.node
            if node_obj is None:
                continue
            submit = (
                getattr(node_obj, "submit_order", None)
                or getattr(node_obj, "create_order", None)
                or getattr(node_obj, "send_order", None)
            )
            if not callable(submit):
                continue
            try:
                self._call_with_signature(submit, payload)
                self._logger.debug("Submitted order via node %s", node_key)
                return
            except Exception as exc:  # pragma: no cover - defensive guard
                self._logger.debug(
                    "Nautilus node %s rejected order submission: %s", node_key, exc
                )

        self._logger.warning("Unable to submit order via Nautilus – no compatible node")

    def cancel_order(self, instructions: Dict[str, Any]) -> None:
        """Forward an order cancel request to a running Nautilus node."""

        if not self.active_nodes:
            self._logger.debug("No Nautilus nodes active – skipping cancel request.")
            return

        target_id = instructions.get("node_id")
        candidates: Iterable[Tuple[str, EngineNodeHandle]]
        if isinstance(target_id, str) and target_id in self.active_nodes:
            candidates = [(target_id, self.active_nodes[target_id])]
        else:
            candidates = list(self.active_nodes.items())

        payload = {
            key: value for key, value in instructions.items() if key != "node_id"
        }

        for node_key, entry in candidates:
            node_obj = entry.node
            if node_obj is None:
                continue
            cancel = (
                getattr(node_obj, "cancel_order", None)
                or getattr(node_obj, "cancel_orders", None)
                or getattr(node_obj, "cancel", None)
            )
            if not callable(cancel):
                continue
            try:
                self._call_with_signature(cancel, payload)
                self._logger.debug("Submitted cancel via node %s", node_key)
                return
            except Exception as exc:  # pragma: no cover - defensive guard
                self._logger.debug(
                    "Nautilus node %s rejected cancel request: %s", node_key, exc
                )

        self._logger.warning("Unable to cancel order via Nautilus – no compatible node")

    def get_historical_bars(
        self,
        *,
        instrument_id: str,
        granularity: str,
        limit: Optional[int] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Attempt to retrieve historical bars via the running Nautilus nodes."""

        if not self.active_nodes:
            return None

        start_dt = self._parse_iso8601(start)
        end_dt = self._parse_iso8601(end)
        limit_value = self._coerce_positive_int(limit)

        params = {
            "instrument_id": instrument_id,
            "granularity": granularity,
            "limit": limit_value,
            "start": start,
            "end": end,
        }

        data_attributes = (
            "data_engine",
            "data",
            "data_api",
            "cache",
        )
        method_candidates = (
            "get_historical_bars",
            "fetch_historical_bars",
            "query_bars",
            "get_bars",
            "bars",
        )

        for node_key, entry in self.active_nodes.items():
            node_obj = entry.node
            if node_obj is None:
                continue
            for attribute in data_attributes:
                provider = getattr(node_obj, attribute, None)
                if provider is None:
                    continue
                for method_name in method_candidates:
                    method = getattr(provider, method_name, None)
                    if not callable(method):
                        continue
                    try:
                        prepared = self._prepare_historical_call_params(
                            method_name=method_name,
                            base_params=params,
                            instrument_id=instrument_id,
                            granularity=granularity,
                            start_dt=start_dt,
                            end_dt=end_dt,
                            limit=limit_value,
                        )
                        result = self._call_with_signature(method, prepared)
                    except Exception as exc:
                        self._logger.debug(
                            "Node %s data provider %s.%s failed: %s",
                            node_key,
                            attribute,
                            method_name,
                            exc,
                        )
                        continue
                    if result is None:
                        continue
                    try:
                        payload = self._normalise_historical_bars(
                            result,
                            instrument_id=instrument_id,
                            granularity=granularity,
                            start_dt=start_dt,
                            end_dt=end_dt,
                            limit=limit_value,
                        )
                    except Exception as exc:
                        self._logger.debug(
                            "Node %s returned unsupported bar payload via %s.%s: %s",
                            node_key,
                            attribute,
                            method_name,
                            exc,
                        )
                        continue
                    if payload is not None:
                        return payload
        return None

    def _coerce_positive_int(self, value: Optional[int]) -> Optional[int]:
        """Return ``value`` as a positive integer or ``None`` if invalid."""

        if value is None:
            return None
        try:
            coerced = int(value)
        except (TypeError, ValueError):
            return None
        return coerced if coerced > 0 else None

    def _prepare_historical_call_params(
        self,
        *,
        method_name: str,
        base_params: Dict[str, Any],
        instrument_id: str,
        granularity: str,
        start_dt: Optional[datetime],
        end_dt: Optional[datetime],
        limit: Optional[int],
    ) -> Dict[str, Any]:
        """Return parameters adapted for the concrete Nautilus data accessor."""

        prepared = dict(base_params)
        method_lower = method_name.lower()

        if method_lower == "query_bars":
            prepared = {
                "instrument_ids": [instrument_id],
            }
            if start_dt is not None:
                prepared["start"] = self._datetime_to_unix_nanos(start_dt)
            if end_dt is not None:
                prepared["end"] = self._datetime_to_unix_nanos(end_dt)
            if limit is not None:
                prepared["limit"] = limit
            return prepared

        prepared.setdefault("instrument_id", instrument_id)
        prepared.setdefault("granularity", granularity)
        if start_dt is not None and not prepared.get("start"):
            prepared["start"] = self._format_datetime(start_dt)
        if end_dt is not None and not prepared.get("end"):
            prepared["end"] = self._format_datetime(end_dt)
        if limit is not None and not prepared.get("limit"):
            prepared["limit"] = limit
        return prepared

    def _normalise_historical_bars(
        self,
        data: Any,
        *,
        instrument_id: str,
        granularity: str,
        start_dt: Optional[datetime],
        end_dt: Optional[datetime],
        limit: Optional[int],
    ) -> Optional[Dict[str, Any]]:
        """Convert raw Nautilus payloads into the gateway schema."""

        if isinstance(data, dict):
            payload = dict(data)
            bars_raw = payload.get("bars")
            if isinstance(bars_raw, list):
                bars = [
                    bar
                    for bar in (self._serialise_bar(entry) for entry in bars_raw)
                    if bar is not None
                ]
            else:
                bars = []
            bars = self._filter_bars(
                bars, start_dt=start_dt, end_dt=end_dt, limit=limit
            )
            payload["bars"] = bars
            payload.setdefault("instrument_id", instrument_id)
            payload.setdefault("granularity", granularity)
            return payload

        if isinstance(data, (list, tuple, set)) or hasattr(data, "__iter__"):
            try:
                iterable = list(data)  # type: ignore[arg-type]
            except TypeError:
                iterable = []
        else:
            return None

        bars = [
            bar
            for bar in (self._serialise_bar(entry) for entry in iterable)
            if bar is not None
        ]
        bars = self._filter_bars(bars, start_dt=start_dt, end_dt=end_dt, limit=limit)

        return {
            "instrument_id": instrument_id,
            "granularity": granularity,
            "bars": bars,
        }

    def _filter_bars(
        self,
        bars: List[Dict[str, Any]],
        *,
        start_dt: Optional[datetime],
        end_dt: Optional[datetime],
        limit: Optional[int],
    ) -> List[Dict[str, Any]]:
        """Filter the list of bars by time range and limit."""

        filtered: List[Dict[str, Any]] = []
        for bar in bars:
            timestamp = bar.get("timestamp")
            if isinstance(timestamp, str):
                ts_dt = self._parse_iso8601(timestamp)
            else:
                ts_dt = None
            if ts_dt is not None:
                if start_dt is not None and ts_dt < start_dt:
                    continue
                if end_dt is not None and ts_dt > end_dt:
                    continue
            filtered.append(bar)

        filtered.sort(key=lambda item: item.get("timestamp") or "")

        if limit is not None and limit > 0 and len(filtered) > limit:
            filtered = filtered[-limit:]

        return filtered

    def _serialise_bar(self, bar: Any) -> Optional[Dict[str, Any]]:
        """Convert Nautilus bar objects into primitive dictionaries."""

        if bar is None:
            return None

        raw: Optional[Dict[str, Any]]
        if isinstance(bar, dict):
            raw = dict(bar)
        else:
            raw = None
            for attr in ("to_dict", "as_dict", "dict"):
                candidate = getattr(bar, attr, None)
                if callable(candidate):
                    try:
                        result = candidate()
                    except Exception:
                        continue
                    if isinstance(result, dict):
                        raw = result
                        break
            if raw is None:
                extracted: Dict[str, Any] = {}
                for field in (
                    "timestamp",
                    "ts_event",
                    "ts_init",
                    "time",
                    "open",
                    "open_price",
                    "open_px",
                    "high",
                    "high_price",
                    "low",
                    "low_price",
                    "close",
                    "close_price",
                    "volume",
                    "quantity",
                    "qty",
                ):
                    if hasattr(bar, field):
                        try:
                            extracted[field] = getattr(bar, field)
                        except Exception:
                            continue
                raw = extracted if extracted else None

        if raw is None:
            return None

        timestamp = self._normalise_bar_timestamp(
            raw.get("timestamp")
            or raw.get("ts_event")
            or raw.get("ts_init")
            or raw.get("time")
        )
        open_price = self._normalise_bar_value(
            raw.get("open") or raw.get("open_price") or raw.get("open_px")
        )
        high_price = self._normalise_bar_value(raw.get("high") or raw.get("high_price"))
        low_price = self._normalise_bar_value(raw.get("low") or raw.get("low_price"))
        close_price = self._normalise_bar_value(
            raw.get("close") or raw.get("close_price")
        )
        volume = self._normalise_bar_value(
            raw.get("volume") or raw.get("quantity") or raw.get("qty")
        )

        if (
            timestamp is None
            or open_price is None
            or high_price is None
            or low_price is None
            or close_price is None
        ):
            return None

        return {
            "timestamp": timestamp,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume if volume is not None else 0.0,
        }

    def _normalise_bar_value(self, value: Any) -> Optional[float]:
        """Convert Nautilus numeric primitives into floats."""

        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None

        for attr in ("as_double", "as_decimal", "to_double", "to_decimal"):
            candidate = getattr(value, attr, None)
            if callable(candidate):
                try:
                    result = candidate()
                except Exception:
                    continue
                if isinstance(result, Decimal):
                    return float(result)
                if result is not None:
                    try:
                        return float(result)
                    except (TypeError, ValueError):
                        continue

        if hasattr(value, "value"):
            try:
                return float(getattr(value, "value"))
            except (TypeError, ValueError):
                pass

        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    def _normalise_bar_timestamp(self, value: Any) -> Optional[str]:
        """Convert timestamps into ISO-8601 strings."""

        if value is None:
            return None
        if isinstance(value, str):
            parsed = self._parse_iso8601(value)
            if parsed is None:
                return value
            return self._format_datetime(parsed)
        if isinstance(value, datetime):
            return self._format_datetime(value)
        if isinstance(value, (int, float)):
            return self._format_unix_nanos(int(value))
        if hasattr(value, "to_pydatetime"):
            try:
                dt_value = value.to_pydatetime()  # type: ignore[attr-defined]
            except Exception:
                dt_value = None
            if isinstance(dt_value, datetime):
                return self._format_datetime(dt_value)
        if hasattr(value, "value"):
            inner = getattr(value, "value")
            if isinstance(inner, (int, float)):
                return self._format_unix_nanos(int(inner))
        try:
            coerced = float(value)
        except (TypeError, ValueError):
            return None
        return self._format_unix_nanos(int(coerced))

    def _format_unix_nanos(self, nanos: int) -> str:
        seconds, remainder = divmod(int(nanos), 1_000_000_000)
        micros = remainder // 1_000
        dt_value = datetime.fromtimestamp(seconds, tz=timezone.utc).replace(
            microsecond=micros
        )
        return self._format_datetime(dt_value)

    def _datetime_to_unix_nanos(self, value: datetime) -> int:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        delta = value - epoch
        return (
            delta.days * 24 * 60 * 60 * 1_000_000_000
            + delta.seconds * 1_000_000_000
            + delta.microseconds * 1_000
        )

    def _parse_iso8601(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        return parsed

    def _format_datetime(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _configure_node_logging(
        self,
        node: Any,
        node_id: str,
        mode: EngineMode,
    ) -> None:
        if self._nt is None:
            return

        try:
            from nautilus_trader.config import LoggingConfig  # type: ignore
        except Exception:  # pragma: no cover - optional dependency
            return

        try:
            from nautilus_trader.config import LogLevel  # type: ignore
        except Exception:  # pragma: no cover - optional dependency
            LogLevel = None

        try:
            log_path = self._ensure_node_storage(node_id) / f"{mode.value}.log"
            kwargs: Dict[str, Any] = {
                "log_to_stdout": True,
                "log_to_file": True,
                "log_file_path": str(log_path),
            }
            if LogLevel is not None:
                kwargs["log_level"] = getattr(LogLevel, "INFO", "INFO")

            logging_config = LoggingConfig(**kwargs)
            configure = getattr(node, "configure_logging", None)
            if callable(configure):
                configure(logging_config)
        except Exception as exc:  # pragma: no cover - optional integration
            self._logger.debug(
                "Unable to configure Nautilus logging for node %s: %s", node_id, exc
            )

    def _plan_adapters(
        self,
        mode: EngineMode,
        config: Dict[str, Any],
        node_id: str,
        *,
        user_id: Optional[str] = None,
    ) -> List[AdapterPlanEntry]:
        data_sources = config.get("dataSources")
        if not isinstance(data_sources, list):
            return []

        key_refs = [
            ref for ref in config.get("keyReferences", []) if isinstance(ref, dict)
        ]

        plan_by_name: Dict[str, AdapterPlanEntry] = {}
        for source in data_sources:
            if not isinstance(source, dict):
                continue
            identifier = str(source.get("id") or "").strip()
            adapter_type = str(source.get("type") or "").lower()
            adapter_mode = str(source.get("mode") or "").lower() or "read"
            if not identifier or adapter_type != "live":
                continue

            entry: Optional[AdapterPlanEntry]
            kind = identifier.lower()
            if kind.startswith("binance"):
                entry = self._plan_binance_adapter(
                    mode, source, key_refs, node_id, identifier, user_id=user_id
                )
            elif kind.startswith("bybit"):
                entry = self._plan_bybit_adapter(
                    mode, source, key_refs, node_id, identifier, user_id=user_id
                )
            elif kind.startswith("ib") or "interactive" in kind:
                entry = self._plan_ib_adapter(
                    mode, source, key_refs, node_id, identifier, user_id=user_id
                )
            else:
                self._logger.debug(
                    "Node %s has no integration for adapter %s (type=%s mode=%s)",
                    node_id,
                    identifier,
                    adapter_type or "unknown",
                    adapter_mode or "unknown",
                )
                entry = None

            if entry is None:
                continue

            entry.mode = adapter_mode or entry.mode
            entry.identifier = identifier
            if identifier not in entry.sources:
                entry.sources.append(identifier)

            existing = plan_by_name.get(entry.name)
            if existing:
                if (
                    entry.data_factory
                    and entry.data_config
                    and not existing.data_config
                ):
                    existing.data_factory = entry.data_factory
                    existing.data_config = entry.data_config
                if (
                    entry.exec_factory
                    and entry.exec_config
                    and not existing.exec_config
                ):
                    existing.exec_factory = entry.exec_factory
                    existing.exec_config = entry.exec_config
                existing.mode = self._merge_modes(existing.mode, entry.mode)
                existing.sandbox = existing.sandbox or entry.sandbox
                existing.detail.update(entry.detail)
                existing.sources.extend(
                    src for src in entry.sources if src not in existing.sources
                )
            else:
                plan_by_name[entry.name] = entry

        return list(plan_by_name.values())

    def _build_trading_config(
        self, mode: EngineMode, plan: List[AdapterPlanEntry]
    ) -> Any:
        try:
            from nautilus_trader.common import Environment  # type: ignore
            from nautilus_trader.config import TradingNodeConfig  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "Unable to import Nautilus trading configuration"
            ) from exc

        data_clients: Dict[str, Any] = {}
        exec_clients: Dict[str, Any] = {}
        for entry in plan:
            if entry.data_config is not None:
                data_clients[entry.name] = entry.data_config
            if entry.exec_config is not None:
                exec_clients[entry.name] = entry.exec_config

        environment = {
            EngineMode.LIVE: Environment.LIVE,
            EngineMode.SANDBOX: Environment.SANDBOX,
            EngineMode.BACKTEST: Environment.BACKTEST,
        }.get(mode, Environment.LIVE)

        if not data_clients and not exec_clients:
            return TradingNodeConfig(environment=environment)

        return TradingNodeConfig(
            environment=environment,
            data_clients=data_clients,
            exec_clients=exec_clients,
        )

    def _register_adapter_factories(
        self, node: Any, plan: List[AdapterPlanEntry], node_id: str
    ) -> None:
        for entry in plan:
            if entry.data_factory is not None:
                add_data_factory = getattr(node, "add_data_client_factory", None)
                if callable(add_data_factory):
                    try:
                        add_data_factory(entry.name, entry.data_factory)
                    except TypeError:
                        add_data_factory(entry.data_factory)  # type: ignore[misc]
                    except Exception as exc:
                        self._logger.debug(
                            "Unable to register data factory %s for node %s: %s",
                            entry.name,
                            node_id,
                            exc,
                        )
                else:
                    self._logger.debug(
                        "Node %s exposes no data factory hook – %s skipped",
                        node_id,
                        entry.name,
                    )
            if entry.exec_factory is not None:
                add_exec_factory = getattr(node, "add_execution_client_factory", None)
                if callable(add_exec_factory):
                    try:
                        add_exec_factory(entry.name, entry.exec_factory)
                    except TypeError:
                        add_exec_factory(entry.exec_factory)  # type: ignore[misc]
                    except Exception as exc:
                        self._logger.debug(
                            "Unable to register execution factory %s for node %s: %s",
                            entry.name,
                            node_id,
                            exc,
                        )
                else:
                    self._logger.debug(
                        "Node %s exposes no execution factory hook – %s skipped",
                        node_id,
                        entry.name,
                    )

    def _build_adapter_status(
        self, node_id: str, plan: List[AdapterPlanEntry]
    ) -> List[Dict[str, Any]]:
        status: List[Dict[str, Any]] = []
        for entry in plan:
            status.append(
                {
                    "name": entry.name,
                    "identifier": entry.identifier,
                    "mode": entry.mode,
                    "sandbox": entry.sandbox,
                    "sources": list(entry.sources),
                    "state": "starting",
                }
            )
        return status

    def _set_adapter_state(
        self, node_id: str, state: str, *, name: Optional[str] = None
    ) -> None:
        entries = self._adapter_status.get(node_id)
        if not entries:
            return
        for entry in entries:
            if name is not None and entry.get("name") != name:
                continue
            entry["state"] = state

        running = self.active_nodes.get(node_id)
        if running is not None:
            running.adapters = deepcopy(entries)

    def _plan_binance_adapter(
        self,
        mode: EngineMode,
        source: Dict[str, Any],
        key_refs: Iterable[Dict[str, Any]],
        node_id: str,
        identifier: str,
        *,
        user_id: Optional[str] = None,
    ) -> Optional[AdapterPlanEntry]:
        try:
            from nautilus_trader.adapters.binance import (
                BINANCE,
                BinanceAccountType,
                BinanceDataClientConfig,
                BinanceExecClientConfig,
                BinanceKeyType,
                BinanceLiveDataClientFactory,
                BinanceLiveExecClientFactory,
            )  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            self._logger.warning(
                "Node %s unable to import Binance adapters: %s", node_id, exc
            )
            return None

        options = self._extract_options(source)
        sandbox_flag = self._determine_testnet(options, mode)

        credentials = self._resolve_credentials_for_alias(
            "binance", key_refs, user_id=user_id
        )

        account_type = self._parse_enum(
            BinanceAccountType, options.get("accountType"), BinanceAccountType.SPOT
        )
        key_type = self._parse_enum(
            BinanceKeyType, options.get("keyType"), BinanceKeyType.HMAC
        )

        data_config = BinanceDataClientConfig(
            api_key=credentials.get("api_key"),
            api_secret=credentials.get("api_secret"),
            account_type=account_type,
            key_type=key_type,
            testnet=sandbox_flag,
            us=self._is_truthy(options.get("us")),
            base_url_http=options.get("httpEndpoint") or options.get("baseUrlHttp"),
            base_url_ws=options.get("wsEndpoint") or options.get("baseUrlWs"),
        )

        exec_config = None
        exec_factory = None
        mode_lower = str(source.get("mode") or "").lower()
        if mode_lower != "read":
            exec_config = BinanceExecClientConfig(
                api_key=credentials.get("api_key"),
                api_secret=credentials.get("api_secret"),
                account_type=account_type,
                key_type=key_type,
                testnet=sandbox_flag,
                us=self._is_truthy(options.get("us")),
                base_url_http=options.get("httpEndpoint") or options.get("baseUrlHttp"),
                base_url_ws=options.get("execWsEndpoint") or options.get("baseUrlWs"),
            )
            exec_factory = BinanceLiveExecClientFactory

        entry = AdapterPlanEntry(
            name=BINANCE,
            identifier=identifier,
            mode=mode_lower or "read",
            sandbox=sandbox_flag,
            data_factory=BinanceLiveDataClientFactory,
            exec_factory=exec_factory,
            data_config=data_config,
            exec_config=exec_config,
            detail={
                "account_type": getattr(
                    account_type, "value", str(account_type)
                ).lower(),
                "testnet": sandbox_flag,
            },
            sources=[identifier],
        )
        return entry

    def _plan_bybit_adapter(
        self,
        mode: EngineMode,
        source: Dict[str, Any],
        key_refs: Iterable[Dict[str, Any]],
        node_id: str,
        identifier: str,
        *,
        user_id: Optional[str] = None,
    ) -> Optional[AdapterPlanEntry]:
        try:
            from nautilus_trader.adapters.bybit import (
                BYBIT,
                BybitDataClientConfig,
                BybitExecClientConfig,
                BybitLiveDataClientFactory,
                BybitLiveExecClientFactory,
                BybitProductType,
            )  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            self._logger.warning(
                "Node %s unable to import Bybit adapters: %s", node_id, exc
            )
            return None

        options = self._extract_options(source)
        sandbox_flag = self._determine_testnet(options, mode)

        credentials = self._resolve_credentials_for_alias(
            "bybit", key_refs, user_id=user_id
        )

        product_types = self._parse_product_types(
            options.get("productTypes") or options.get("product_types"),
            BybitProductType,
        )

        data_config = BybitDataClientConfig(
            api_key=credentials.get("api_key"),
            api_secret=credentials.get("api_secret"),
            product_types=product_types,
            base_url_http=options.get("httpEndpoint") or options.get("baseUrlHttp"),
            demo=self._is_truthy(options.get("demo")),
            testnet=sandbox_flag,
            recv_window_ms=self._coerce_positive_int(options.get("recvWindowMs")),
        )

        exec_config = None
        exec_factory = None
        mode_lower = str(source.get("mode") or "").lower()
        if mode_lower != "read":
            exec_config = BybitExecClientConfig(
                api_key=credentials.get("api_key"),
                api_secret=credentials.get("api_secret"),
                product_types=product_types,
                base_url_http=options.get("httpEndpoint") or options.get("baseUrlHttp"),
                demo=self._is_truthy(options.get("demo")),
                testnet=sandbox_flag,
                recv_window_ms=self._coerce_positive_int(options.get("recvWindowMs")),
            )
            exec_factory = BybitLiveExecClientFactory

        entry = AdapterPlanEntry(
            name=BYBIT,
            identifier=identifier,
            mode=mode_lower or "read",
            sandbox=sandbox_flag,
            data_factory=BybitLiveDataClientFactory,
            exec_factory=exec_factory,
            data_config=data_config,
            exec_config=exec_config,
            detail={
                "product_types": (
                    [getattr(pt, "value", str(pt)).lower() for pt in product_types]
                    if product_types
                    else []
                ),
                "testnet": sandbox_flag,
            },
            sources=[identifier],
        )
        return entry

    def _plan_ib_adapter(
        self,
        mode: EngineMode,
        source: Dict[str, Any],
        key_refs: Iterable[Dict[str, Any]],
        node_id: str,
        identifier: str,
        *,
        user_id: Optional[str] = None,
    ) -> Optional[AdapterPlanEntry]:
        try:
            from nautilus_trader.adapters.interactive_brokers.common import IB
            from nautilus_trader.adapters.interactive_brokers.config import (
                IBMarketDataTypeEnum,
                InteractiveBrokersDataClientConfig,
                InteractiveBrokersExecClientConfig,
            )  # type: ignore
            from nautilus_trader.adapters.interactive_brokers.factories import (
                InteractiveBrokersLiveDataClientFactory,
                InteractiveBrokersLiveExecClientFactory,
            )  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            self._logger.warning(
                "Node %s unable to import Interactive Brokers adapters: %s",
                node_id,
                exc,
            )
            return None

        options = self._extract_options(source)
        sandbox_flag = self._determine_testnet(options, mode) or self._is_truthy(
            options.get("paper")
        )

        credentials = self._resolve_credentials_for_alias(
            "interactive", key_refs, user_id=user_id
        )

        ibg_host = str(options.get("host") or options.get("ibgHost") or "127.0.0.1")
        port_candidate = options.get("port") or options.get("ibgPort")
        ibg_port = self._coerce_positive_int(port_candidate)
        if ibg_port is None:
            ibg_port = 4002 if sandbox_flag else 4001

        client_id_value = options.get("clientId") or options.get("ibgClientId")
        ibg_client_id = self._coerce_positive_int(client_id_value) or 1

        market_data_type_value = options.get("marketDataType") or options.get(
            "market_data_type"
        )
        market_data_type = self._parse_enum(
            IBMarketDataTypeEnum,
            market_data_type_value,
            getattr(
                InteractiveBrokersDataClientConfig,
                "market_data_type",
                IBMarketDataTypeEnum.REALTIME,
            ),
        )

        data_config = InteractiveBrokersDataClientConfig(
            ibg_host=ibg_host,
            ibg_port=ibg_port,
            ibg_client_id=ibg_client_id,
            market_data_type=market_data_type,
        )

        account_id = credentials.get("api_key") or options.get("accountId")

        exec_config = None
        exec_factory = None
        mode_lower = str(source.get("mode") or "").lower()
        if mode_lower != "read":
            exec_config = InteractiveBrokersExecClientConfig(
                ibg_host=ibg_host,
                ibg_port=ibg_port,
                ibg_client_id=ibg_client_id,
                account_id=account_id,
            )
            exec_factory = InteractiveBrokersLiveExecClientFactory

        entry = AdapterPlanEntry(
            name=IB,
            identifier=identifier,
            mode=mode_lower or "read",
            sandbox=sandbox_flag,
            data_factory=InteractiveBrokersLiveDataClientFactory,
            exec_factory=exec_factory,
            data_config=data_config,
            exec_config=exec_config,
            detail={
                "host": ibg_host,
                "port": ibg_port,
                "client_id": ibg_client_id,
                "paper_trading": sandbox_flag,
                "market_data_type": getattr(
                    market_data_type, "name", str(market_data_type)
                ).lower(),
                "account_id": account_id,
            },
            sources=[identifier],
        )
        return entry

    def _merge_modes(self, first: str, second: str) -> str:
        first = (first or "").strip().lower()
        second = (second or "").strip().lower()
        if first == second:
            return first or "read"
        combined = {first, second}
        if "both" in combined:
            return "both"
        if combined == {"read", "write"}:
            return "both"
        if "write" in combined:
            return "write"
        return "read"

    def _extract_options(self, source: Dict[str, Any]) -> Dict[str, Any]:
        options = source.get("options")
        if isinstance(options, dict):
            return dict(options)
        return {}

    def _determine_testnet(self, options: Dict[str, Any], mode: EngineMode) -> bool:
        if mode == EngineMode.SANDBOX:
            return True
        for key in ("testnet", "sandbox", "paper", "demo"):
            if self._is_truthy(options.get(key)):
                return True
        environment = str(options.get("environment") or "").lower()
        return environment in {"sandbox", "paper", "testnet", "demo"}

    def _parse_enum(self, enum_cls: Any, value: Any, default: Any) -> Any:
        if isinstance(value, enum_cls):
            return value
        if value is None:
            return default
        text = str(value).strip()
        if not text:
            return default
        candidate = text.replace("-", "_").replace(" ", "_").upper()
        try:
            return enum_cls[candidate]
        except KeyError:
            for member in enum_cls:
                if str(getattr(member, "value", "")).upper() == candidate:
                    return member
        return default

    def _parse_product_types(self, values: Any, enum_cls: Any) -> Optional[List[Any]]:
        if values is None:
            return None
        if isinstance(values, (str, enum_cls)):
            values = [values]
        result: List[Any] = []
        for item in values:
            member = self._parse_enum(enum_cls, item, None)
            if member is not None and member not in result:
                result.append(member)
        return result or None

    def _is_truthy(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            return lowered in {
                "1",
                "true",
                "yes",
                "y",
                "on",
                "sandbox",
                "paper",
                "test",
                "testnet",
                "demo",
            }
        return False

    def _resolve_credentials_for_alias(
        self,
        alias: str,
        key_refs: Iterable[Dict[str, Any]],
        *,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        credentials: Dict[str, Any] = {}
        reference = self._find_key_reference(alias, key_refs)
        if not reference:
            return credentials

        key_id = str(reference.get("keyId") or "").strip()
        if not key_id:
            return credentials

        payload = self._load_api_key_credentials(key_id, user_id=user_id)
        if payload:
            credentials.update(payload)

        env_api_key = retrieve_key(key_id, "api_key")
        env_api_secret = retrieve_key(key_id, "api_secret")
        env_passphrase = retrieve_key(key_id, "passphrase")

        if env_api_key:
            credentials.setdefault("api_key", env_api_key)
        if env_api_secret:
            credentials.setdefault("api_secret", env_api_secret)
        if env_passphrase:
            credentials.setdefault("passphrase", env_passphrase)

        credentials["key_id"] = key_id

        secret_value = credentials.get("api_secret")
        if isinstance(secret_value, dict):
            passphrase = credentials.get("passphrase")
            if not passphrase:
                env_pass = retrieve_key(key_id, "passphrase")
                if env_pass:
                    credentials["passphrase"] = env_pass
                    passphrase = env_pass
            if isinstance(passphrase, str) and passphrase:
                expected_hash = credentials.get("passphrase_hash")
                if isinstance(expected_hash, str):
                    try:
                        hashed = self._hash_passphrase(passphrase)
                        if hashed.lower() != expected_hash.lower():
                            self._logger.warning(
                                "Passphrase verification failed for credential key %s",
                                key_id,
                            )
                    except Exception:
                        pass
                decrypted = self._decrypt_secret_payload(
                    secret_value, passphrase, key_id
                )
                if decrypted is not None:
                    credentials["api_secret"] = decrypted
                else:
                    credentials.pop("api_secret", None)
            else:
                self._logger.warning(
                    "Credential key %s requires passphrase to decrypt secret", key_id
                )
                credentials.pop("api_secret", None)

        return credentials

    def _load_api_key_credentials(
        self, key_id: str, user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        if (
            not key_id
            or self._database_url is None
            or create_async_engine is None
            or async_sessionmaker is None
            or select is None
            or ApiKey is None
        ):
            return None

        user_id_int: Optional[int] = None
        if user_id is not None:
            try:
                user_id_int = int(user_id)
            except (TypeError, ValueError):
                user_id_int = None

        async def _execute() -> Optional[Dict[str, Any]]:
            if self._api_session_factory is None:
                try:
                    engine = create_async_engine(self._database_url, future=True)
                except Exception as exc:  # pragma: no cover - optional dependency
                    self._logger.debug(
                        "Unable to initialise database engine for credentials: %s",
                        exc,
                    )
                    return None
                self._api_engine = engine
                self._api_session_factory = async_sessionmaker(
                    engine, expire_on_commit=False
                )

            assert self._api_session_factory is not None

            async with self._api_session_factory() as session:  # type: ignore[misc]
                stmt = select(ApiKey).where(ApiKey.key_id == key_id)
                if user_id_int is not None:
                    stmt = stmt.where(ApiKey.user_id == user_id_int)
                result = await session.execute(stmt)
                record = result.scalars().first()
                if record is None:
                    return None
                payload = self._decode_secret_payload(record.secret_enc)
                if payload is None:
                    return None
                return {
                    "api_key": payload.get("api_key"),
                    "api_secret": payload.get("api_secret"),
                    "passphrase_hash": payload.get("passphrase_hash"),
                    "passphrase_hint": payload.get("passphrase_hint"),
                }

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_execute())
        except Exception as exc:  # pragma: no cover - defensive logging
            self._logger.debug("Failed to load credentials for key %s: %s", key_id, exc)
            return None
        finally:
            loop.close()

    def _decode_secret_payload(self, secret_enc: bytes) -> Optional[Dict[str, Any]]:
        if not secret_enc or self._encryption_key is None:
            return None
        try:
            plaintext = decrypt(secret_enc, key=self._encryption_key)
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.warning("Failed to decrypt credential payload: %s", exc)
            return None
        try:
            data = json.loads(plaintext.decode("utf-8"))
        except ValueError:
            self._logger.warning("Credential payload for stored secret is malformed")
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _decrypt_secret_payload(
        self, payload: Dict[str, Any], passphrase: str, key_id: str
    ) -> Optional[str]:
        try:
            salt = base64.b64decode(payload.get("salt", ""))
            iv = base64.b64decode(payload.get("iv", ""))
            ciphertext = base64.b64decode(payload.get("ciphertext", ""))
        except Exception as exc:
            self._logger.debug(
                "Credential secret decoding failed for key %s: %s", key_id, exc
            )
            return None

        iterations = payload.get("iterations") or 100_000
        try:
            iterations = int(iterations)
        except (TypeError, ValueError):
            iterations = 100_000
        iterations = max(iterations, 1)

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=iterations,
        )
        key = kdf.derive(passphrase.encode("utf-8"))
        cipher = AESGCM(key)
        try:
            plaintext = cipher.decrypt(iv, ciphertext, None)
        except Exception as exc:
            self._logger.warning(
                "Unable to decrypt API secret for key %s: %s", key_id, exc
            )
            return None
        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError:
            return plaintext.decode("utf-8", "ignore")

    def _hash_passphrase(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _find_key_reference(
        self, prefix: str, key_refs: Iterable[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        lowered_prefix = prefix.lower()
        for ref in key_refs:
            alias = str(ref.get("alias") or "").lower()
            if alias.startswith(lowered_prefix):
                return ref
        for ref in key_refs:
            key_id = str(ref.get("keyId") or "").lower()
            if key_id.startswith(lowered_prefix):
                return ref
        return None

    def list_adapter_status(self) -> List[Dict[str, Any]]:
        snapshot: List[Dict[str, Any]] = []
        for node_id, entries in self._adapter_status.items():
            for entry in entries:
                snapshot.append(
                    {
                        "node_id": node_id,
                        "name": entry.get("name"),
                        "identifier": entry.get("identifier"),
                        "mode": entry.get("mode"),
                        "state": entry.get("state"),
                        "sandbox": entry.get("sandbox", False),
                        "sources": entry.get("sources", []),
                    }
                )
        return snapshot

    def get_node_adapter_status(self, node_id: str) -> List[Dict[str, Any]]:
        return deepcopy(self._adapter_status.get(node_id, []))

    def _map_event_to_topic(self, event_name: str) -> Tuple[str, str]:
        lowered = event_name.lower()
        if "order" in lowered:
            return "engine.orders", "order"
        if any(keyword in lowered for keyword in ("fill", "execution", "trade")):
            return "engine.executions", "execution"
        if "position" in lowered or "portfolio" in lowered:
            return "engine.portfolio", "position"
        if any(keyword in lowered for keyword in ("risk", "margin", "limit")):
            return "engine.risk.alerts", "alert"
        if any(
            keyword in lowered for keyword in ("lifecycle", "status", "stop", "start")
        ):
            return "engine.nodes", "lifecycle"
        return "engine.nautilus.events", "payload"

    def _resolve_nt_type(self, *path: str) -> Any:
        module = self._nt
        if module is None:
            return None
        for name in path[:-1]:
            module = getattr(module, name, None)
            if module is None:
                return None
        return getattr(module, path[-1], None)

    def _serialise_positions(self, positions: Any) -> Any:
        if isinstance(positions, dict):
            return {
                str(key): self._serialise_event(value)
                for key, value in positions.items()
            }
        if isinstance(positions, (list, tuple, set)):
            return [self._serialise_event(item) for item in positions]
        return self._serialise_event(positions)

    def _build_risk_alert(
        self,
        event: Any,
        node_id: str,
        serialised: Dict[str, Any],
    ) -> Dict[str, Any]:
        event_name = getattr(event, "__class__", type(event)).__name__
        lowered = event_name.lower()
        category = "limit_breach"
        severity = "high"
        if "margin" in lowered:
            category = "margin_call"
            severity = "critical"
        elif "limit" in lowered:
            category = "limit_breach"
            severity = "medium"
        elif "risk" in lowered:
            category = "limit_breach"

        title = getattr(event, "title", None) or event_name.replace("_", " ")
        message = (
            getattr(event, "message", None)
            or serialised.get("message")
            or serialised.get("detail")
            or title
        )

        alert_payload: Dict[str, Any] = {
            "alert_id": uuid.uuid4().hex,
            "category": category,
            "title": title,
            "message": message,
            "severity": severity,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "context": serialised,
            "node_id": node_id,
        }
        return alert_payload

    def _serialise_event(self, event: Any) -> Dict[str, Any]:
        if event is None:
            return {"value": None}

        for attr in ("as_dict", "to_dict", "dict"):
            candidate = getattr(event, attr, None)
            if callable(candidate):
                try:
                    result = candidate()
                    if isinstance(result, dict):
                        return result
                except Exception:
                    continue
        mapping = getattr(event, "__dict__", None)
        if isinstance(mapping, dict):
            serialised: Dict[str, Any] = {}
            for key, value in mapping.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    serialised[key] = value
                else:
                    serialised[key] = repr(value)
            return serialised
        return {"repr": repr(event)}

    def _call_with_signature(
        self,
        method: Callable[..., Any],
        arguments: Dict[str, Any],
    ) -> Any:
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            signature = None

        if signature is not None:
            kwargs: Dict[str, Any] = {}
            for name, parameter in signature.parameters.items():
                if name == "self":
                    continue
                if name in arguments and arguments[name] is not None:
                    kwargs[name] = arguments[name]
            if kwargs:
                return method(**kwargs)

        ordered_keys = ["instrument_id", "granularity", "start", "end", "limit"]
        ordered_args = [
            arguments[key]
            for key in ordered_keys
            if key in arguments and arguments[key] is not None
        ]
        if ordered_args:
            return method(*ordered_args)

        return method()

    def store_node_config(
        self,
        *,
        node_id: str,
        mode: EngineMode,
        config: Dict[str, Any],
        source: Optional[str] = None,
        fmt: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """Persist a validated configuration document under ``.gateway``."""

        node_dir = self._ensure_node_storage(node_id)

        preferred_fmt = (fmt or "json").lower()
        extension = "json"
        if preferred_fmt in {"yaml", "yml"} and yaml is not None:
            extension = "yaml"

        config_path = node_dir / f"{mode.value}.{extension}"
        try:
            if extension == "json":
                config_path.write_text(
                    json.dumps(config, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            else:
                with config_path.open("w", encoding="utf-8") as handle:
                    yaml.safe_dump(  # type: ignore[no-untyped-call]
                        config,
                        handle,
                        sort_keys=False,
                        allow_unicode=True,
                    )
        except OSError as exc:
            raise EngineConfigStorageError(
                f"Unable to persist configuration for node '{node_id}': {exc}"
            ) from exc

        meta_payload: Dict[str, Any] = {
            "node_id": node_id,
            "mode": mode.value,
            "format": extension,
            "source": source or "gateway",
            "saved_at": datetime.utcnow().isoformat() + "Z",
        }
        if metadata:
            for key, value in metadata.items():
                if key in meta_payload:
                    continue
                meta_payload[key] = value

        meta_path = node_dir / f"{mode.value}.meta.json"
        try:
            meta_path.write_text(
                json.dumps(meta_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise EngineConfigStorageError(
                f"Unable to persist configuration metadata for node '{node_id}': {exc}"
            ) from exc

        return config_path


def build_engine_service(bus: Optional[EngineEventBus] = None) -> NautilusEngineService:
    """Factory helper used across the gateway to construct the engine wrapper."""

    return NautilusEngineService(bus=bus)
