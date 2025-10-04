from fastapi import FastAPI
from .settings import settings
from .nautilus_service import svc

app = FastAPI(title="Amadeus Gateway")

@app.get("/health")
def health(): return {"status": "ok", "env": settings.env}

@app.post("/nodes/backtest/start")
def start_bt(): return svc.start_backtest().__dict__

@app.post("/nodes/live/start")
def start_live(): return svc.start_live().__dict__

@app.get("/nodes")
def nodes(): return [n.__dict__ for n in svc.list_nodes()]
