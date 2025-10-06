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
import inspect
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import json
import logging
from pathlib import Path
from datetime import datetime
import threading
from typing import Any, AsyncIterator, Callable, Dict, Iterable, Optional, Tuple

try:  # pragma: no cover - optional dependency during unit tests
    import nautilus_trader as nt  # type: ignore
except Exception:  # pragma: no cover - optional dependency during unit tests
    nt = None

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
        self._nt = nt
        self._storage_root = storage_root or self._default_storage_root()
        self._logger = logging.getLogger(__name__)
        self._nodes_running: Dict[str, Dict[str, Any]] = {}

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

    def launch_trading_node(
        self,
        mode: EngineMode,
        config: Dict[str, Any],
        *,
        node_id: Optional[str] = None,
    ) -> Any:
        """Instantiate and start a Nautilus :class:`TradingNode` in the background."""

        if self._nt is None:
            raise RuntimeError(
                "nautilus_trader package is not available – unable to start engine nodes."
            )

        try:
            from nautilus_trader.trading.node import TradingNode  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "nautilus_trader.trading.node.TradingNode could not be imported"
            ) from exc

        safe_config = deepcopy(config)
        resolved_node_id = (
            node_id
            or str(safe_config.get("id") or "").strip()
            or f"node-{len(self._nodes_running) + 1}"
        )
        safe_config.setdefault("id", resolved_node_id)

        if resolved_node_id in self._nodes_running:
            raise RuntimeError(f"Node '{resolved_node_id}' is already running")

        node = TradingNode(config=safe_config)

        self._configure_node_logging(node, resolved_node_id, mode)
        self._configure_adapters(node, mode, safe_config, resolved_node_id)

        def runner() -> None:
            try:
                node.start()
            except Exception as exc:  # pragma: no cover - defensive guard
                self._logger.exception(
                    "Nautilus node %s terminated unexpectedly: %s", resolved_node_id, exc
                )

        thread = threading.Thread(
            target=runner,
            name=f"nautilus-node-{resolved_node_id}",
            daemon=True,
        )
        thread.start()

        self._nodes_running[resolved_node_id] = {
            "node": node,
            "mode": mode,
            "thread": thread,
        }

        try:
            self.attach_bus_listeners(node, resolved_node_id)
        except Exception as exc:  # pragma: no cover - best-effort wiring
            self._logger.debug(
                "Failed to attach Nautilus event listeners for node %s: %s",
                resolved_node_id,
                exc,
            )

        return node

    def attach_bus_listeners(self, node: Any, node_id: str) -> None:
        """Bridge Nautilus event callbacks to the gateway event bus."""

        dispatcher = getattr(node, "event_dispatcher", None)
        if dispatcher is None:
            self._logger.debug(
                "Node %s exposes no event dispatcher – skipping bus bridge.", node_id
            )
            return

        subscribe_all = getattr(dispatcher, "subscribe_all", None)
        if not callable(subscribe_all):
            self._logger.debug(
                "Nautilus dispatcher for node %s has no subscribe_all method.", node_id
            )
            return

        def forward(event: Any) -> None:
            event_name = getattr(event, "__class__", type(event)).__name__
            topic, field = self._map_event_to_topic(event_name)
            payload = {
                "event": event_name,
                "node_id": node_id,
            }
            serialised = self._serialise_event(event)
            if isinstance(serialised, dict):
                payload[field] = serialised
            else:
                payload[field] = {"repr": repr(serialised)}
            self.publish(topic, payload)

        try:
            subscribe_all(forward)
        except TypeError:
            try:
                subscribe_all(callback=forward)
            except Exception as exc:  # pragma: no cover - optional API shapes
                self._logger.debug(
                    "Unable to subscribe to Nautilus events for node %s: %s", node_id, exc
                )
        except Exception as exc:  # pragma: no cover - optional API shapes
            self._logger.debug(
                "Unable to subscribe to Nautilus events for node %s: %s", node_id, exc
            )

    def submit_order(self, instructions: Dict[str, Any]) -> None:
        """Forward order instructions to a running Nautilus trading node if available."""

        if not self._nodes_running:
            self._logger.debug("No Nautilus nodes active – skipping order submission.")
            return

        target_id = instructions.get("node_id")
        candidates: Iterable[Tuple[str, Dict[str, Any]]]
        if isinstance(target_id, str) and target_id in self._nodes_running:
            candidates = [(target_id, self._nodes_running[target_id])]
        else:
            candidates = list(self._nodes_running.items())

        payload = {key: value for key, value in instructions.items() if key != "node_id"}

        for node_key, entry in candidates:
            node_obj = entry.get("node")
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

        if not self._nodes_running:
            return None

        params = {
            "instrument_id": instrument_id,
            "granularity": granularity,
            "limit": limit,
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

        for node_key, entry in self._nodes_running.items():
            node_obj = entry.get("node")
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
                        result = self._call_with_signature(method, params)
                    except Exception as exc:
                        self._logger.debug(
                            "Node %s data provider %s.%s failed: %s",
                            node_key,
                            attribute,
                            method_name,
                            exc,
                        )
                        continue
                    if result is not None:
                        return result
        return None

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

        config_module = getattr(self._nt, "config", None)
        LoggingConfig = getattr(config_module, "LoggingConfig", None)
        LogLevel = getattr(config_module, "LogLevel", None)
        if LoggingConfig is None:
            return

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

    def _configure_adapters(
        self,
        node: Any,
        mode: EngineMode,
        config: Dict[str, Any],
        node_id: str,
    ) -> None:
        data_sources = config.get("dataSources")
        if not isinstance(data_sources, list):
            return

        for source in data_sources:
            if not isinstance(source, dict):
                continue
            identifier = str(source.get("id") or "").strip()
            adapter_type = str(source.get("type") or "").lower()
            adapter_mode = str(source.get("mode") or "").lower()
            if not identifier:
                continue

            self._logger.debug(
                "Node %s adapter placeholder – id=%s type=%s mode=%s",
                node_id,
                identifier,
                adapter_type or "unknown",
                adapter_mode or "unknown",
            )

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
        if any(keyword in lowered for keyword in ("lifecycle", "status", "stop", "start")):
            return "engine.nodes", "lifecycle"
        return "engine.nautilus.events", "payload"

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

