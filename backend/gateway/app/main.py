from fastapi import FastAPI
from .nautilus_service import svc
from .settings import settings

app = FastAPI(title="Amadeus Gateway")

@app.get("/health")
def health():
    return {"status": "ok", "env": settings.env}

@app.post("/nodes/backtest/start")
def start_backtest():
    node = svc.start_backtest()
    return {"node": node.__dict__}

@app.post("/nodes/live/start")
def start_live():
    node = svc.start_live()
    return {"node": node.__dict__}

@app.get("/nodes")
def get_nodes():
    return {"nodes": [n.__dict__ for n in svc.list_nodes()]}
