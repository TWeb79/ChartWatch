from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import app_selector, ctrader_check, storage
from . import config as cfg_module
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


@app.post("/api/config")
async def config_update(request: Request):
    body = await request.json()
    log_event(log, "api_config_update", {"body": body})
    cfg = cfg_module.update(body)
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


@app.get("/api/mcp/verify")
async def mcp_verify():
    scheduler = _state.get("scheduler")
    if not scheduler or not scheduler.mcp:
        return {"error": "MCP client not initialized"}
    result = await scheduler.mcp.verify()
    return result


@app.get("/api/mcp/accounts")
async def mcp_accounts():
    scheduler = _state.get("scheduler")
    if not scheduler or not scheduler.mcp:
        return {"accounts": [], "selectedAccountId": None, "selectedBalance": None}
    accounts = await scheduler.mcp.get_accounts()
    account_id = scheduler.cfg.get("ctrader_mcp", {}).get("account_id")
    selected_balance = None
    if account_id is not None:
        try:
            balance_result = await scheduler.mcp.call("get_balance", {})
            if isinstance(balance_result, dict):
                selected_balance = balance_result.get("balance")
        except Exception:
            pass
    return {
        "accounts": accounts,
        "selectedAccountId": account_id,
        "selectedBalance": selected_balance,
    }


@app.post("/api/config/ctrader-account")
async def set_ctrader_account(request: Request):
    body = await request.json()
    account_id = body.get("account_id")
    if account_id is None:
        return JSONResponse({"error": "account_id required"}, status_code=400)
    log_event(log, "api_config_ctrader_account", {"account_id": account_id})
    cfg = cfg_module.update({"ctrader_mcp": {"account_id": account_id}})
    _state["scheduler"].cfg = cfg
    _state["scheduler"].mcp.account_id = account_id
    return cfg


@app.get("/api/health")
async def health_check():
    scheduler = _state.get("scheduler")
    mcp_ok = False
    ollama_ok = False
    mcp_error = None
    ollama_error = None

    if scheduler and scheduler.mcp:
        try:
            mcp_result = await scheduler.mcp.verify()
            mcp_ok = mcp_result.get("reachable", False)
            mcp_error = mcp_result.get("error")
        except Exception as e:
            mcp_error = str(e)

    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            ollama_ok = resp.status == 200
    except Exception as e:
        ollama_error = str(e)

    status = "ok" if (mcp_ok and ollama_ok) else "degraded"
    return {
        "status": status,
        "mcp": {"ok": mcp_ok, "error": mcp_error},
        "ollama": {"ok": ollama_ok, "error": ollama_error},
    }


@app.get("/api/health/prerequisites")
async def prerequisites_check():
    scheduler = _state.get("scheduler")
    if not scheduler:
        return {"ok": False, "error": "scheduler not initialized"}
    cfg = scheduler.cfg
    return ctrader_check.check_prerequisites(cfg)


@app.get("/api/history")
def get_history(limit: int = 50):
    limit = max(1, min(limit, 500))
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
    allowed_origins = {"http://localhost:8056", "http://127.0.0.1:8056"}
    origin = websocket.headers.get("origin", "")
    if origin not in allowed_origins:
        log_event(log, "ws_rejected", {"origin": origin})
        await websocket.close(code=1008)
        return
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
