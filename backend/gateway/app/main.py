from __future__ import annotations

import asyncio, json, random
from typing import List

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .settings import settings
from .nautilus_service import svc, NodeHandle


class NodeLaunchStrategyParameter(BaseModel):
    key: str
    value: str


class NodeLaunchStrategy(BaseModel):
    id: str
    name: str
    parameters: List[NodeLaunchStrategyParameter] = Field(default_factory=list)


class NodeLaunchDataSource(BaseModel):
    id: str
    label: str
    type: str
    mode: str
    enabled: bool = True


class NodeLaunchKeyReference(BaseModel):
    alias: str
    keyId: str
    required: bool = True


class NodeLaunchConstraints(BaseModel):
    maxRuntimeMinutes: int | None = None
    maxDrawdownPercent: float | None = None
    autoStopOnError: bool = True
    concurrencyLimit: int | None = None


class NodeLaunchPayload(BaseModel):
    type: str
    strategy: NodeLaunchStrategy
    dataSources: List[NodeLaunchDataSource] = Field(default_factory=list)
    keyReferences: List[NodeLaunchKeyReference] = Field(default_factory=list)
    constraints: NodeLaunchConstraints = Field(default_factory=NodeLaunchConstraints)


def build_launch_detail(payload: NodeLaunchPayload) -> str:
    parts: List[str] = []
    strategy_summary = f"Strategy {payload.strategy.name} ({payload.strategy.id})"
    if payload.strategy.parameters:
        params = ", ".join(f"{param.key}={param.value}" for param in payload.strategy.parameters)
        strategy_summary += f" [{params}]"
    parts.append(strategy_summary)

    if payload.dataSources:
        sources = ", ".join(f"{source.label or source.id}" for source in payload.dataSources)
        parts.append(f"Data: {sources}")

    if payload.keyReferences:
        keys = ", ".join(key.alias for key in payload.keyReferences)
        parts.append(f"Keys: {keys}")

    constraint_bits: List[str] = []
    constraints = payload.constraints
    if constraints.maxRuntimeMinutes is not None:
        constraint_bits.append(f"max {constraints.maxRuntimeMinutes} min")
    if constraints.maxDrawdownPercent is not None:
        constraint_bits.append(f"drawdown {constraints.maxDrawdownPercent}%")
    if constraints.concurrencyLimit is not None:
        constraint_bits.append(f"limit {constraints.concurrencyLimit}")
    if constraints.autoStopOnError:
        constraint_bits.append("auto-stop")
    if constraint_bits:
        parts.append("Constraints: " + ", ".join(constraint_bits))

    node_type = payload.type.capitalize()
    parts.insert(0, f"{node_type} node")
    return " | ".join(parts)

app = FastAPI(title="Amadeus Gateway")

# 👇 Разрешаем localhost и 127.0.0.1 (Angular dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok", "env": settings.env}

@app.get("/core/info")
def core_info():
    return svc.core_info()

@app.get("/nodes")
def list_nodes():
    return {"nodes": [svc.as_dict(n) for n in svc.list_nodes()]}

@app.post("/nodes/backtest/start")
def start_backtest():
    node: NodeHandle = svc.start_backtest()
    return {"node": svc.as_dict(node)}

@app.post("/nodes/live/start")
def start_live():
    node: NodeHandle = svc.start_live()
    return {"node": svc.as_dict(node)}


@app.post("/nodes/launch")
def launch_node(payload: NodeLaunchPayload):
    node_type = payload.type.lower()
    detail = build_launch_detail(payload)
    if node_type == "backtest":
        node = svc.start_backtest(detail=detail)
    elif node_type == "live":
        node = svc.start_live(detail=detail)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported node type '{payload.type}'")
    return {"node": svc.as_dict(node)}

@app.post("/nodes/{node_id}/stop")
def stop_node(node_id: str):
    try:
        node = svc.stop_node(node_id)
        return {"node": svc.as_dict(node)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.websocket("/ws/nodes")
async def ws_nodes(ws: WebSocket):
    await ws.accept()
    pnl: dict[str, float] = {}
    lat: dict[str, float] = {}
    try:
        while True:
            nodes = [svc.as_dict(n) for n in svc.list_nodes()]
            for n in nodes:
                nid = n["id"]
                if nid not in pnl:
                    pnl[nid] = 0.0
                    lat[nid] = random.uniform(3, 15)
                pnl[nid] += random.gauss(0, 0.5)
                lat[nid] = max(1.0, lat[nid] + random.uniform(-0.8, 0.8))
                n["metrics"] = {"pnl": round(pnl[nid], 2), "latency_ms": round(lat[nid], 1)}
            await ws.send_text(json.dumps({"nodes": nodes}))
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
