from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .settings import settings
from .nautilus_service import svc, NodeHandle

app = FastAPI(title="Amadeus Gateway")

# CORS: разрешаем локальный Angular dev-сервер
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
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
