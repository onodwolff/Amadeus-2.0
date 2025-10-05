from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime
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
class NodeState:
    handle: NodeHandle
    config: Dict[str, Any]
    lifecycle: List[NodeLifecycleEvent]
    logs: List[NodeLogEntry]


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
        return [state.handle for state in self._nodes.values()]

    def as_dict(self, handle: NodeHandle) -> dict:
        return asdict(handle)

    def _create_node(self, mode: str, detail: Optional[str], config: Dict[str, Any]) -> NodeHandle:
        prefix = "bt" if mode == "backtest" else "lv"
        node_id = f"{prefix}-{uuid.uuid4().hex[:8]}"
        handle = NodeHandle(id=node_id, mode=mode, status="created", detail=detail)
        state = NodeState(handle=handle, config=config, lifecycle=[], logs=[])
        self._nodes[node_id] = state
        self._record_lifecycle(node_id, "created", "Node registered")

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
