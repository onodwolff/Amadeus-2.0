from dataclasses import dataclass

@dataclass
class NodeHandle:
    id: str
    mode: str  # "backtest" | "live"

class NautilusService:
    def __init__(self):
        self.nodes: dict[str, NodeHandle] = {}

    def start_backtest(self) -> NodeHandle:
        h = NodeHandle(id="bt-1", mode="backtest")
        self.nodes[h.id] = h
        return h

    def start_live(self) -> NodeHandle:
        h = NodeHandle(id="lv-1", mode="live")
        self.nodes[h.id] = h
        return h

    def list_nodes(self):
        return list(self.nodes.values())

svc = NautilusService()
