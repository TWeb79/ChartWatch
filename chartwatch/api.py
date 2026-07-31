from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config as cfg_module
from . import app_selector, storage
from .logger import get_logger, log_event
from .scheduler import Scheduler

log = get_logger("chartwatch.api")

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
    _state["scheduler_task"] = asyncio.create_task(scheduler.start())


@app.on_event("shutdown")
async def shutdown():
    scheduler = _state.get("scheduler")
    scheduler_task = _state.get("scheduler_task")
    if scheduler:
        scheduler.stop()
    if scheduler_task:
        try:
            await asyncio.wait_for(scheduler_task, timeout=5)
        except asyncio.TimeoutError:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
    if scheduler and scheduler.mcp:
        try:
            await scheduler.mcp.disconnect()
        except Exception:
            pass


@app.get("/api/windows")
def get_windows():
    return app_selector.list_windows()


@app.post("/api/config/target-window")
def set_target_window(window_id: int, title: str):
    log_event(log, "api_config_target_window", {"window_id": window_id, "title": title})
    cfg = cfg_module.update({"target_window": title, "target_window_id": window_id})
    _state["scheduler"].cfg = cfg
    return cfg


@app.post("/api/config/interval")
def set_interval(minutes: int):
    scheduler = _state["scheduler"]
    min_interval_s = scheduler.min_interval_seconds()
    min_minutes = max(1, int(min_interval_s / 60) + (1 if min_interval_s % 60 > 0 else 0))
    if minutes < min_minutes:
        log_event(log, "api_config_interval_rejected", {
            "requested": minutes,
            "min": min_minutes,
        })
        return {
            "ok": False,
            "message": f"interval_minutes must be >= {min_minutes} (avg Ollama + 30s safety margin)",
            "min_minutes": min_minutes,
        }
    log_event(log, "api_config_interval", {"minutes": minutes})
    cfg = cfg_module.update({"interval_minutes": minutes})
    scheduler.cfg = cfg
    return cfg


@app.post("/api/config/auto-approve")
def set_auto_approve(enabled: bool):
    log_event(log, "api_config_auto_approve", {"enabled": enabled})
    cfg = cfg_module.update({"approval": {"auto_approve": enabled}})
    _state["scheduler"].cfg = cfg
    return cfg


@app.post("/api/scheduler/start")
async def scheduler_start():
    log_event(log, "api_scheduler_start", {})
    scheduler = _state["scheduler"]
    asyncio.create_task(scheduler.trigger_cycle())
    return {"ok": True}


@app.post("/api/scheduler/stop")
def scheduler_stop():
    log_event(log, "api_scheduler_stop", {})
    scheduler = _state["scheduler"]
    scheduler.stop()
    return {"ok": True}


@app.get("/api/scheduler/timing")
def scheduler_timing():
    scheduler = _state["scheduler"]
    avg_s = scheduler.avg_ollama_time()
    min_interval_s = scheduler.min_interval_seconds()
    configured_s = scheduler.cfg["interval_minutes"] * 60
    return {
        "avg_ollama_time_s": round(avg_s, 2),
        "min_interval_s": round(min_interval_s, 2),
        "configured_interval_s": configured_s,
        "effective_interval_s": round(max(configured_s, min_interval_s), 2),
        "ollama_samples": len(scheduler._ollama_times),
    }


@app.get("/api/history")
def get_history(limit: int = 50):
    log_event(log, "api_history", {"limit": limit})
    return _state["store"].recent(limit)


@app.post("/api/approve/{cycle_id}")
def approve(cycle_id: int):
    log_event(log, "api_approve", {"cycle_id": cycle_id})
    ok = _state["scheduler"].resolve_pending(cycle_id, "approved")
    return {"ok": ok}


@app.post("/api/deny/{cycle_id}")
def deny(cycle_id: int):
    log_event(log, "api_deny", {"cycle_id": cycle_id})
    ok = _state["scheduler"].resolve_pending(cycle_id, "denied")
    return {"ok": ok}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    log_event(log, "ws_client_connected", {})
    async with _ws_lock:
        _ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keepalive / unused
    except WebSocketDisconnect:
        log_event(log, "ws_client_disconnected", {})
        async with _ws_lock:
            try:
                _ws_clients.remove(websocket)
            except ValueError:
                pass


static_dir = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

screenshots_dir = Path(__file__).resolve().parent.parent / "screenshots"
app.mount("/screenshots", StaticFiles(directory=str(screenshots_dir)), name="screenshots")


@app.get("/")
def index():
    return FileResponse(str(static_dir / "index.html"))
