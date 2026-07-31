from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config as cfg_module
from . import app_selector, storage
from .scheduler import Scheduler

app = FastAPI()

_state: dict[str, Any] = {}
_ws_clients: list[WebSocket] = []
_ws_lock = asyncio.Lock()


async def _broadcast(event_type: str, payload: dict):
    dead = []
    async with _ws_lock:
        clients = list(_ws_clients)
    for ws in clients:
        try:
            await ws.send_json({"type": event_type, "payload": payload})
        except Exception:
            dead.append(ws)
    if dead:
        async with _ws_lock:
            for ws in dead:
                try:
                    _ws_clients.remove(ws)
                except ValueError:
                    pass


@app.on_event("startup")
async def startup():
    cfg = cfg_module.load()
    store = storage.Storage(cfg["storage"]["db_path"])
    scheduler = Scheduler(cfg, store, _broadcast)
    _state["cfg"] = cfg
    _state["store"] = store
    _state["scheduler"] = scheduler
    asyncio.create_task(scheduler.start())


@app.get("/api/windows")
def get_windows():
    return app_selector.list_windows()


@app.post("/api/config/target-window")
def set_target_window(window_id: int, title: str):
    cfg = cfg_module.update({"target_window": title, "target_window_id": window_id})
    _state["scheduler"].cfg = cfg
    return cfg


@app.post("/api/config/interval")
def set_interval(minutes: int):
    cfg = cfg_module.update({"interval_minutes": minutes})
    _state["scheduler"].cfg = cfg
    return cfg


@app.post("/api/config/auto-approve")
def set_auto_approve(enabled: bool):
    cfg = cfg_module.update({"approval": {"auto_approve": enabled}})
    _state["scheduler"].cfg = cfg
    return cfg


@app.post("/api/scheduler/start")
async def scheduler_start():
    scheduler = _state["scheduler"]
    asyncio.create_task(scheduler.trigger_cycle())
    return {"ok": True}


@app.post("/api/scheduler/stop")
def scheduler_stop():
    scheduler = _state["scheduler"]
    scheduler.stop()
    return {"ok": True}


@app.get("/api/history")
def get_history(limit: int = 50):
    return _state["store"].recent(limit)


@app.post("/api/approve/{cycle_id}")
def approve(cycle_id: int):
    ok = _state["scheduler"].resolve_pending(cycle_id, "approved")
    return {"ok": ok}


@app.post("/api/deny/{cycle_id}")
def deny(cycle_id: int):
    ok = _state["scheduler"].resolve_pending(cycle_id, "denied")
    return {"ok": ok}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    async with _ws_lock:
        _ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keepalive / unused
    except WebSocketDisconnect:
        async with _ws_lock:
            try:
                _ws_clients.remove(websocket)
            except ValueError:
                pass


static_dir = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
def index():
    return FileResponse(str(static_dir / "index.html"))
