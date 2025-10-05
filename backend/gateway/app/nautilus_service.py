from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import sys
import uuid
from typing import Dict, List, Optional

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
    mode: str   # "backtest" | "live"
    status: str # "created" | "running" | "stopped" | "error"
    detail: Optional[str] = None

class NautilusService:
    def __init__(self) -> None:
        self._nodes: Dict[str, NodeHandle] = {}

    def core_info(self) -> dict:
        return {"nautilus_version": NT_VERSION, "available": nt is not None}

    def start_backtest(
        self,
        symbol: str = "BTCUSDT",
        venue: str = "BINANCE",
        bar: str = "1m",
        detail: Optional[str] = None,
    ) -> NodeHandle:
        node_id = f"bt-{uuid.uuid4().hex[:8]}"
        handle = NodeHandle(id=node_id, mode="backtest", status="created")
        if nt is None:
            handle.status = "error"
            handle.detail = "Nautilus core not available. Install package into backend venv."
            self._nodes[node_id] = handle
            return handle
        handle.status = "running"
        handle.detail = detail or f"Backtest node prepared (symbol={symbol}, venue={venue}, bar={bar})"
        self._nodes[node_id] = handle
        return handle

    def start_live(self, venue: str = "BINANCE", detail: Optional[str] = None) -> NodeHandle:
        node_id = f"lv-{uuid.uuid4().hex[:8]}"
        handle = NodeHandle(id=node_id, mode="live", status="created")
        if nt is None:
            handle.status = "error"
            handle.detail = "Nautilus core not available. Install package into backend venv."
            self._nodes[node_id] = handle
            return handle
        handle.status = "running"
        handle.detail = detail or f"Live node prepared (venue={venue}). Configure adapters to proceed."
        self._nodes[node_id] = handle
        return handle

    def stop_node(self, node_id: str) -> NodeHandle:
        handle = self._nodes.get(node_id)
        if not handle:
            raise ValueError(f"Node '{node_id}' not found")
        handle.status = "stopped"
        return handle

    def list_nodes(self) -> List[NodeHandle]:
        return list(self._nodes.values())

    def as_dict(self, handle: NodeHandle) -> dict:
        return asdict(handle)

svc = NautilusService()
print(f"[NautilusService] core={NT_VERSION} available={nt is not None}")
