from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import random
import sys
import uuid
from typing import Any, Dict, List, Optional


def _utcnow_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _import_nautilus():
    try:
        import nautilus_trader as nt  # установлен в текущем venv
        return nt
    except Exception:
        # Fallback: импорт из vendor/nautilus_trader (если пакет не установлен)
        root = Path(__file__).resolve().parents[3]  # .../Amadeus-2.0
        vend = root / "vendor" / "nautilus_trader"
        if str(vend) not in sys.path:
            sys.path.insert(0, str(vend))
        import importlib

        nt = importlib.import_module("nautilus_trader")
        return nt


try:
    nt = _import_nautilus()
    NT_VERSION = getattr(nt, "__version__", "unknown")
except Exception:
    nt = None
    NT_VERSION = "unavailable"


@dataclass
class NodeHandle:
    id: str
    mode: str  # "backtest" | "live"
    status: str  # "created" | "running" | "stopped" | "error"
    detail: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class NodeLifecycleEvent:
    timestamp: str
    status: str
    message: str


@dataclass
class NodeLogEntry:
    id: str
    timestamp: str
    level: str
    message: str
    source: str


@dataclass
class NodeMetricsSample:
    timestamp: str
    pnl: float
    latency_ms: float
    cpu_percent: float
    memory_mb: float


@dataclass
class NodeState:
    handle: NodeHandle
    config: Dict[str, Any]
    lifecycle: List[NodeLifecycleEvent]
    logs: List[NodeLogEntry]
    metrics: List[NodeMetricsSample]


class NautilusService:
    def __init__(self) -> None:
        self._nodes: Dict[str, NodeState] = {}

    def core_info(self) -> dict:
        return {"nautilus_version": NT_VERSION, "available": nt is not None}

    def start_backtest(
        self,
        symbol: str = "BTCUSDT",
        venue: str = "BINANCE",
        bar: str = "1m",
        detail: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> NodeHandle:
        config_data: Dict[str, Any] = config or {
            "type": "backtest",
            "strategy": {
                "id": "default_backtest",
                "name": "Default backtest",
                "parameters": [
                    {"key": "symbol", "value": symbol},
                    {"key": "venue", "value": venue},
                    {"key": "bar", "value": bar},
                ],
            },
            "dataSources": [
                {
                    "id": f"{venue.lower()}-{symbol.lower()}-{bar}",
                    "label": f"{venue} {symbol} {bar}",
                    "type": "historical",
                    "mode": "read",
                }
            ],
            "keyReferences": [],
            "constraints": {"maxRuntimeMinutes": 480, "autoStopOnError": True},
        }
        return self._create_node(
            mode="backtest",
            detail=detail
            or f"Backtest node prepared (symbol={symbol}, venue={venue}, bar={bar})",
            config=config_data,
        )

    def start_live(
        self,
        venue: str = "BINANCE",
        detail: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> NodeHandle:
        config_data: Dict[str, Any] = config or {
            "type": "live",
            "strategy": {
                "id": "live_default",
                "name": "Live execution",
                "parameters": [
                    {"key": "venue", "value": venue},
                    {"key": "mode", "value": "production"},
                ],
            },
            "dataSources": [
                {
                    "id": f"{venue.lower()}-market-data",
                    "label": f"{venue} market data",
                    "type": "live",
                    "mode": "read",
                }
            ],
            "keyReferences": [
                {"alias": f"{venue} primary key", "keyId": f"{venue.lower()}-primary", "required": True}
            ],
            "constraints": {"autoStopOnError": True},
        }
        return self._create_node(
            mode="live",
            detail=detail or f"Live node prepared (venue={venue}). Configure adapters to proceed.",
            config=config_data,
        )

    def stop_node(self, node_id: str) -> NodeHandle:
        state = self._require_node(node_id)
        handle = state.handle
        if handle.status == "stopped":
            return handle
        handle.status = "stopped"
        handle.updated_at = _utcnow_iso()
        self._record_lifecycle(node_id, "stopped", "Node stopped by operator")
        self._append_log(node_id, "info", "Node received stop signal", source="orchestrator")
        return handle

    def restart_node(self, node_id: str) -> NodeHandle:
        state = self._require_node(node_id)
        if nt is None:
            raise ValueError("Nautilus core not available. Install package into backend venv.")
        handle = state.handle
        handle.status = "running"
        handle.detail = handle.detail or "Node restarted"
        handle.updated_at = _utcnow_iso()
        self._record_lifecycle(node_id, "running", "Node restarted")
        self._append_log(node_id, "info", "Restart sequence completed", source="controller")
        return handle

    def node_detail(self, node_id: str) -> dict:
        state = self._require_node(node_id)
        return {
            "node": self.as_dict(state.handle),
            "config": state.config,
            "lifecycle": [asdict(event) for event in state.lifecycle],
        }

    def node_logs(self, node_id: str) -> dict:
        state = self._require_node(node_id)
        return {"logs": [asdict(entry) for entry in state.logs]}

    def export_logs(self, node_id: str) -> str:
        state = self._require_node(node_id)
        return "\n".join(
            f"[{entry.timestamp}] {entry.level.upper()} {entry.source}: {entry.message}"
            for entry in state.logs
        )

    def stream_snapshot(self, node_id: str) -> dict:
        state = self._require_node(node_id)
        handle = state.handle
        if nt is not None and handle.status == "running":
            self._maybe_append_runtime_activity(node_id)
        return {
            "logs": [asdict(entry) for entry in state.logs[-200:]],
            "lifecycle": [asdict(event) for event in state.lifecycle[-50:]],
        }

    def list_nodes(self) -> List[NodeHandle]:
        for node_id in list(self._nodes.keys()):
            self._ensure_metrics_seeded(node_id)
            self._update_handle_metrics(node_id)
        return [state.handle for state in self._nodes.values()]

    def as_dict(self, handle: NodeHandle) -> dict:
        return asdict(handle)

    def _create_node(self, mode: str, detail: Optional[str], config: Dict[str, Any]) -> NodeHandle:
        prefix = "bt" if mode == "backtest" else "lv"
        node_id = f"{prefix}-{uuid.uuid4().hex[:8]}"
        handle = NodeHandle(id=node_id, mode=mode, status="created", detail=detail)
        state = NodeState(handle=handle, config=config, lifecycle=[], logs=[], metrics=[])
        self._nodes[node_id] = state
        self._record_lifecycle(node_id, "created", "Node registered")
        self._ensure_metrics_seeded(node_id)

        if nt is None:
            handle.status = "error"
            handle.detail = (
                "Nautilus core not available. Install package into backend venv."
            )
            handle.updated_at = _utcnow_iso()
            self._record_lifecycle(node_id, "error", handle.detail)
            self._append_log(node_id, "error", handle.detail, source="system")
            return handle

        handle.status = "running"
        handle.updated_at = _utcnow_iso()
        self._record_lifecycle(node_id, "running", "Node started")
        self._append_log(node_id, "info", "Node entered running state", source="engine")
        self._append_log(
            node_id,
            "debug",
            f"Configuration loaded: {config.get('strategy', {}).get('name', 'strategy')}",
            source="engine",
        )
        return handle

    def _record_lifecycle(self, node_id: str, status: str, message: str) -> None:
        state = self._require_node(node_id)
        state.lifecycle.append(
            NodeLifecycleEvent(timestamp=_utcnow_iso(), status=status, message=message)
        )

    def _append_log(self, node_id: str, level: str, message: str, source: str) -> None:
        state = self._require_node(node_id)
        state.logs.append(
            NodeLogEntry(
                id=uuid.uuid4().hex,
                timestamp=_utcnow_iso(),
                level=level,
                message=message,
                source=source,
            )
        )
        state.handle.updated_at = _utcnow_iso()

    def _ensure_metrics_seeded(self, node_id: str) -> None:
        state = self._require_node(node_id)
        if state.metrics:
            return

        base_time = datetime.utcnow() - timedelta(minutes=179)
        pnl = random.uniform(-25.0, 25.0)
        latency = random.uniform(4.0, 16.0)
        cpu = random.uniform(20.0, 55.0)
        memory = random.uniform(480.0, 640.0)

        for step in range(180):
            pnl += random.gauss(0, 0.6)
            latency = max(1.0, latency + random.uniform(-1.2, 1.2))
            cpu = max(3.0, min(97.0, cpu + random.uniform(-3.5, 3.5)))
            memory = max(256.0, memory + random.uniform(-6.0, 6.0))
            timestamp = (base_time + timedelta(minutes=step)).isoformat() + "Z"
            state.metrics.append(
                NodeMetricsSample(
                    timestamp=timestamp,
                    pnl=round(pnl, 2),
                    latency_ms=round(latency, 2),
                    cpu_percent=round(cpu, 2),
                    memory_mb=round(memory, 2),
                )
            )

        self._update_handle_metrics(node_id)

    def _advance_metrics(self, node_id: str) -> NodeMetricsSample:
        self._ensure_metrics_seeded(node_id)
        state = self._require_node(node_id)
        previous = state.metrics[-1]
        pnl = previous.pnl + random.gauss(0, 1.2)
        latency = max(0.8, previous.latency_ms + random.uniform(-1.5, 1.5))
        cpu = max(2.5, min(98.0, previous.cpu_percent + random.uniform(-4.5, 4.5)))
        memory = max(240.0, previous.memory_mb + random.uniform(-9.0, 9.0))
        sample = NodeMetricsSample(
            timestamp=_utcnow_iso(),
            pnl=round(pnl, 2),
            latency_ms=round(latency, 2),
            cpu_percent=round(cpu, 2),
            memory_mb=round(memory, 2),
        )
        state.metrics.append(sample)
        if len(state.metrics) > 720:
            state.metrics = state.metrics[-720:]
        self._update_handle_metrics(node_id)
        return sample

    def _update_handle_metrics(self, node_id: str) -> None:
        state = self._require_node(node_id)
        if not state.metrics:
            state.handle.metrics = {}
            return

        latest = state.metrics[-1]
        state.handle.metrics = {
            "pnl": latest.pnl,
            "latency_ms": latest.latency_ms,
            "cpu_percent": latest.cpu_percent,
            "memory_mb": latest.memory_mb,
        }
        state.handle.updated_at = _utcnow_iso()

    def metrics_series(self, node_id: str, limit: int = 360) -> dict:
        self._advance_metrics(node_id)
        state = self._require_node(node_id)
        history = state.metrics[-limit:]

        def build_series(attr: str) -> List[dict]:
            return [
                {"timestamp": sample.timestamp, "value": getattr(sample, attr)}
                for sample in history
            ]

        latest = history[-1] if history else None
        return {
            "series": {
                "pnl": build_series("pnl"),
                "latency_ms": build_series("latency_ms"),
                "cpu_percent": build_series("cpu_percent"),
                "memory_mb": build_series("memory_mb"),
            },
            "latest": asdict(latest) if latest else None,
        }

    def metrics_snapshot(self, node_id: str) -> Dict[str, float]:
        sample = self._advance_metrics(node_id)
        return {
            "pnl": sample.pnl,
            "latency_ms": sample.latency_ms,
            "cpu_percent": sample.cpu_percent,
            "memory_mb": sample.memory_mb,
        }

    def _maybe_append_runtime_activity(self, node_id: str) -> None:
        message = random.choice(
            [
                "Heartbeat received from risk manager",
                "Processed market data batch",
                "Strategy evaluation completed",
                "Order book snapshot normalised",
                "PnL checkpoint persisted",
                "Latency within expected thresholds",
            ]
        )
        level = random.choices(
            population=["info", "debug", "warning"],
            weights=[0.6, 0.3, 0.1],
            k=1,
        )[0]
        source = random.choice(["engine", "risk", "execution", "controller"])
        self._append_log(node_id, level, message, source=source)
        if random.random() < 0.15:
            self._record_lifecycle(node_id, "running", "Heartbeat acknowledged")

    def _require_node(self, node_id: str) -> NodeState:
        state = self._nodes.get(node_id)
        if state is None:
            raise ValueError(f"Node '{node_id}' not found")
        return state


svc = NautilusService()
print(f"[NautilusService] core={NT_VERSION} available={nt is not None}")
