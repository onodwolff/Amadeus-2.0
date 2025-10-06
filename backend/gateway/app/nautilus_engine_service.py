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
import contextlib
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from datetime import datetime
import threading
from typing import Any, AsyncIterator, Dict, Iterable, Optional

try:  # pragma: no cover - optional dependency during unit tests
    import nautilus_trader as _nt  # type: ignore
except Exception:  # pragma: no cover - optional dependency during unit tests
    _nt = None

try:  # pragma: no cover - optional dependency for YAML parsing
    import yaml
except Exception:  # pragma: no cover - optional dependency during unit tests
    yaml = None


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
    LIVE = "live"


@dataclass(frozen=True)
class EngineNodeLaunch:
    """Payload describing a requested node launch."""

    mode: EngineMode
    detail: str
    config: Dict[str, Any]


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
    ) -> None:
        self._bus = bus or EngineEventBus()
        self._nt = _nt
        self._storage_root = storage_root or self._default_storage_root()

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
            errors.append("Field 'type' must be a string with value 'backtest' or 'live'.")
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

