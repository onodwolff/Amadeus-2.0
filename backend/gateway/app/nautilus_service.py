from __future__ import annotations

# Amadeus 2.0 – Nautilus integration service (backtest/live handles)
# Этот модуль даёт простой сервис для управления "узлами" Nautilus:
#  - старт/листинг backtest и live (live пока заглушка)
#  - аккуратный импорт ядра Nautilus (из установленного пакета ИЛИ из vendor/)
#  - хранение хэндлов узлов в памяти
#
# Примечание: чтобы импорт точно работал из venv backend’а,
# активируйте его и установите ядро:
#   (WSL) cd /mnt/c/Users/Madwolff/Desktop/Amadeus-2.0/backend
#   source .venv/bin/activate
#   pip install -e ../vendor/nautilus_trader
#
# Либо используйте «fallback» импорт из vendor/ (см. ниже).

from dataclasses import dataclass, asdict
from pathlib import Path
import sys
import uuid
from typing import Dict, List, Optional


# ---------- аккуратный импорт Nautilus ----------
def _import_nautilus():
    try:
        import nautilus_trader as nt  # установлен в текущий venv (предпочтительно)
        return nt
    except Exception:
        # Fallback: добавить путь к vendor/nautilus_trader и попробовать снова
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
except Exception as e:
    nt = None
    NT_VERSION = "unavailable"
    # не бросаем исключение на импорте: сервис сможет отвечать health’ом
    # и сообщать, что ядро не доступно


# ---------- доменные структуры ----------
@dataclass
class NodeHandle:
    id: str
    mode: str   # "backtest" | "live"
    status: str # "created" | "running" | "stopped" | "error"
    detail: Optional[str] = None


# ---------- основной сервис ----------
class NautilusService:
    def __init__(self) -> None:
        # в памяти держим активные узлы
        self._nodes: Dict[str, NodeHandle] = {}

    # Метаданные о ядре
    def core_info(self) -> dict:
        return {
            "nautilus_version": NT_VERSION,
            "available": nt is not None,
        }

    # Старт простого backtest-узла (демо-хэндл; запуск движка подключим по мере готовности данных)
    def start_backtest(self, symbol: str = "BTCUSDT", venue: str = "BINANCE", bar: str = "1m") -> NodeHandle:
        node_id = f"bt-{uuid.uuid4().hex[:8]}"
        handle = NodeHandle(id=node_id, mode="backtest", status="created")

        if nt is None:
            handle.status = "error"
            handle.detail = "Nautilus core not available. Install package into backend venv."
            self._nodes[node_id] = handle
            return handle

        # Здесь можно создать и сохранить контекст движка (отложенно, чтобы не блокировать запрос)
        # Пример (псевдо, без run()):
        # from nautilus_trader.backtest.engine import BacktestEngine
        # from nautilus_trader.model.identifiers import InstrumentId
        # engine = BacktestEngine()
        # engine.add_instrument(InstrumentId(symbol=symbol, venue=venue))
        # (добавить стратегию и источники данных перед run)
        handle.status = "running"
        handle.detail = f"Backtest node prepared (symbol={symbol}, venue={venue}, bar={bar})"
        self._nodes[node_id] = handle
        return handle

    # Старт live-узла (пока заглушка, без реальных ключей/адаптеров)
    def start_live(self, venue: str = "BINANCE") -> NodeHandle:
        node_id = f"lv-{uuid.uuid4().hex[:8]}"
        handle = NodeHandle(id=node_id, mode="live", status="created")

        if nt is None:
            handle.status = "error"
            handle.detail = "Nautilus core not available. Install package into backend venv."
            self._nodes[node_id] = handle
            return handle

        # Тут будет инициализация Trading Node + адаптеров (Binance/Bybit),
        # сейчас ставим заглушку статуса:
        handle.status = "running"
        handle.detail = f"Live node prepared (venue={venue}). Configure adapters to proceed."
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


# ---------- singleton сервиса ----------
svc = NautilusService()

# Лог при импорте модуля
print(f"[NautilusService] core={NT_VERSION} available={nt is not None}")
