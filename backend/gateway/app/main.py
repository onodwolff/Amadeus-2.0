from __future__ import annotations

import asyncio, json, random
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .settings import settings
from .nautilus_service import svc, NodeHandle

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
