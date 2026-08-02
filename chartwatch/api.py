"""FastAPI application: serves the dashboard UI, REST API, and WebSocket
real-time events for the ChartWatch trading assistant.

Author: Inventions4All - github:TWeb79
Version: 1.2.0  (deployment: 2026-08-02)
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import app_selector, ctrader_check, storage
from . import config as cfg_module
from .llm_utils import filter_vision_models
from .logger import get_logger, log_event
from .scheduler import Scheduler

log = get_logger("chartwatch.api")

app = FastAPI()

_state: dict[str, Any] = {}
_ws_clients: list[WebSocket] = []
_ws_lock = asyncio.Lock()

# Cache for filtered LLM models (populated at startup by test_models task)
_filtered_llm_models: dict[str, Any] = {}

# Rate-limiting: prevent rapid re-calling of /api/llm/models/test
# (which triggers a provider API call). Min 30 seconds between manual tests.
_last_model_test_time: float = 0.0
MODEL_TEST_MIN_INTERVAL_S: float = 30.0


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


async def _test_and_cache_models() -> dict[str, Any]:
    """Fetch all models from the configured LLM provider, test each for
    availability + vision capability, and cache the filtered result.

    This runs once at application startup. If the provider is unreachable,
    the cache is left empty and the endpoint will return an error.

    If a cached JSON file (``<provider>_models.json``) exists in the project
    root, it is loaded instead of re-fetching from the provider. If no cache
    file exists, the test runs and writes the filtered results to the file
    for subsequent startups.

    While the test is running, a WebSocket ``models_testing`` event is broadcast
    so the frontend can show a yellow "Analyzing models..." status.
    """
    global _filtered_llm_models

    cfg = cfg_module.load()
    provider = cfg.get("provider", "ollama")
    llm_cfg = cfg.get(provider, {})
    selected_model = cfg.get("llm_model", llm_cfg.get("model", ""))

    # Check for existing cache file
    project_root = Path(__file__).resolve().parent.parent
    cache_file = project_root / f"{provider}_models.json"

    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as f:
                cached = json.loads(f.read())
            _filtered_llm_models = cached
            _filtered_llm_models["selected_model"] = selected_model
            log_event(log, "llm_models_loaded_from_cache", {
                "provider": provider,
                "cached_count": len(cached.get("models", [])),
            })
            await _broadcast("models_ready", {"provider": provider, "model_count": len(cached.get("models", []))})
            return _filtered_llm_models
        except Exception as e:
            log_event(log, "llm_models_cache_load_error", {"error": str(e)})

    # No cache file — run the test (broadcast status to frontend)
    await _broadcast("models_testing", {"provider": provider, "status": "analyzing models"})

    try:
        if provider == "ollama":
            host = llm_cfg.get("host", "http://localhost:11434")
            url = host.rstrip("/") + "/api/tags"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            all_models = [m.get("name", m.get("model", "")) for m in data.get("models", [])]
        elif provider == "nvidia":
            base_url = llm_cfg.get("base_url", "https://integrate.api.nvidia.com/v1")
            api_key = llm_cfg.get("api_key", "")
            url = base_url.rstrip("/") + "/models"
            req = urllib.request.Request(url, method="GET")
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            all_models = [m.get("id", "") for m in data.get("data", [])]
        else:
            all_models = []

        filtered = await filter_vision_models(all_models, provider)
        _filtered_llm_models = {
            "provider": provider,
            "selected_model": selected_model,
            "models": filtered,
            "total_fetched": len(all_models),
            "total_filtered": len(filtered),
        }

        # Persist to cache file for next startup
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(_filtered_llm_models, f, indent=2)
            log_event(log, "llm_models_cache_written", {
                "provider": provider,
                "file": str(cache_file),
                "model_count": len(filtered),
            })
        except Exception as e:
            log_event(log, "llm_models_cache_write_error", {"error": str(e)})

        log_event(log, "llm_models_cached", {
            "provider": provider,
            "total_fetched": len(all_models),
            "total_filtered": len(filtered),
        })
        await _broadcast("models_ready", {"provider": provider, "model_count": len(filtered)})
    except Exception as e:
        log_event(log, "llm_models_cache_error", {"provider": provider, "error": str(e)})
        _filtered_llm_models = {
            "provider": provider,
            "selected_model": selected_model,
            "models": [],
            "error": str(e),
        }
        await _broadcast("models_error", {"provider": provider, "error": str(e)})


@app.on_event("startup")
async def startup():
    cfg = cfg_module.load()
    store = storage.Storage(cfg["storage"]["db_path"])
    scheduler = Scheduler(cfg, store, _broadcast)
    _state["cfg"] = cfg
    _state["store"] = store
    _state["scheduler"] = scheduler
    _state["scheduler_task"] = asyncio.create_task(scheduler.start())
    # Run model availability + vision test once at startup (non-blocking)
    asyncio.create_task(_test_and_cache_models())


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
    account_id = scheduler.cfg.get("ctrader_mcp", {}).get("account_id")
    try:
        accounts = await scheduler.mcp.get_accounts()
    except Exception as e:
        log_event(log, "mcp_accounts_error", {"error": str(e)})
        accounts = []
    selected_balance = None
    if account_id is not None:
        # Prefer the balance embedded in the accounts list for the selected
        # account — the MCP get_balance call without an account_id argument
        # returns the currently active cTrader account's balance, which may
        # differ from the account the user selected in ChartWatch.
        selected_account = next(
            (a for a in accounts if a.get("id") == account_id), None
        )
        if selected_account and selected_account.get("balance") is not None:
            selected_balance = selected_account.get("balance")
        else:
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


@app.get("/api/health/llm")
async def llm_health_check():
    """Check reachability of the configured LLM provider (Ollama or NVIDIA NIM).

    Returns:
        Dict with ``provider``, ``model``, ``reachable`` (bool), and
        ``error`` (str | None).
    """
    cfg = cfg_module.load()
    provider = cfg.get("provider", "ollama")
    llm_cfg = cfg.get("ollama") if provider == "ollama" else cfg.get("nvidia", {})
    model = cfg.get("llm_model", llm_cfg.get("model", ""))

    if provider == "ollama":
        host = llm_cfg.get("host", "http://localhost:11434")
        url = host.rstrip("/") + "/api/tags"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                reachable = resp.status == 200
            log_event(log, "llm_health_ok", {"provider": provider, "model": model})
            return {"provider": provider, "model": model, "reachable": reachable, "error": None}
        except Exception as e:
            log_event(log, "llm_health_error", {"provider": provider, "error": str(e)})
            return {"provider": provider, "model": model, "reachable": False, "error": str(e)}

    if provider == "nvidia":
        base_url = llm_cfg.get("base_url", "https://integrate.api.nvidia.com/v1")
        api_key = llm_cfg.get("api_key", "")
        url = base_url.rstrip("/") + "/models"
        try:
            req = urllib.request.Request(url, method="GET")
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                reachable = resp.status == 200
            log_event(log, "llm_health_ok", {"provider": provider, "model": model})
            return {"provider": provider, "model": model, "reachable": reachable, "error": None}
        except Exception as e:
            log_event(log, "llm_health_error", {"provider": provider, "error": str(e)})
            return {"provider": provider, "model": model, "reachable": False, "error": str(e)}

    log_event(log, "llm_health_unknown_provider", {"provider": provider})
    return {"provider": provider, "model": model, "reachable": False, "error": f"Unknown provider: {provider}"}


@app.get("/api/llm/models")
async def llm_models():
    """List available models for the configured LLM provider.

    Returns cached results from the startup model test if available,
    otherwise fetches fresh from the provider and applies vision/free filtering.

    Returns:
        Dict with ``provider``, ``selected_model``, and ``models``
        (list of filtered model strings sorted alphabetically).
    """
    if _filtered_llm_models and "models" in _filtered_llm_models:
        current_cfg = cfg_module.load()
        current_provider = current_cfg.get("provider", "ollama")
        current_selected = current_cfg.get("llm_model", current_cfg.get(current_provider, {}).get("model", ""))
        # Update selected_model in case it changed since startup
        result = dict(_filtered_llm_models)
        result["selected_model"] = current_selected
        return result

    # Fallback: fetch fresh if cache is empty (e.g. test hasn't run yet)
    cfg = cfg_module.load()
    provider = cfg.get("provider", "ollama")
    llm_cfg = cfg.get(provider, {})
    selected_model = cfg.get("llm_model", llm_cfg.get("model", ""))

    try:
        if provider == "ollama":
            host = llm_cfg.get("host", "http://localhost:11434")
            url = host.rstrip("/") + "/api/tags"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            all_models = [m.get("name", m.get("model", "")) for m in data.get("models", [])]
        elif provider == "nvidia":
            base_url = llm_cfg.get("base_url", "https://integrate.api.nvidia.com/v1")
            api_key = llm_cfg.get("api_key", "")
            url = base_url.rstrip("/") + "/models"
            req = urllib.request.Request(url, method="GET")
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            all_models = [m.get("id", "") for m in data.get("data", [])]
        else:
            all_models = []

        filtered = await filter_vision_models(all_models, provider)
        return {"provider": provider, "selected_model": selected_model, "models": filtered}
    except Exception as e:
        log_event(log, "llm_models_error", {"provider": provider, "error": str(e)})
        return {"provider": provider, "selected_model": selected_model, "models": [], "error": str(e)}


@app.post("/api/llm/model")
async def set_llm_model(request: Request):
    """Set the LLM model for the configured provider.

    Persists ``llm_model`` in config.yaml so the selection survives restarts.
    """
    body = await request.json()
    model = body.get("model", "")
    if not model:
        return JSONResponse({"error": "model required"}, status_code=400)
    log_event(log, "api_llm_model_set", {"model": model})
    cfg = cfg_module.update({"llm_model": model})
    return {"ok": True, "llm_model": cfg.get("llm_model")}


@app.get("/api/llm/models/test")
async def llm_models_test():
    """Re-run the model availability + vision test and refresh the cache.

    Fetches all models from the configured LLM provider, filters out
    unavailable / non-vision / paid models, and caches the result.

    Rate-limited to one call per ``MODEL_TEST_MIN_INTERVAL_S`` seconds to
    prevent accidental provider API flooding (DDOS protection).
    """
    global _last_model_test_time
    now = time.monotonic()
    if now - _last_model_test_time < MODEL_TEST_MIN_INTERVAL_S:
        remaining = round(MODEL_TEST_MIN_INTERVAL_S - (now - _last_model_test_time), 1)
        return JSONResponse(
            {"error": f"Rate limited. Try again in {remaining}s.",
             "next_test_in_s": remaining},
            status_code=429,
        )
    _last_model_test_time = now
    await _test_and_cache_models()
    return _filtered_llm_models


@app.get("/api/history")
def get_history(limit: int = 50):
    limit = max(1, min(limit, 500))
    log_event(log, "api_history", {"limit": limit})
    return _state["store"].recent(limit)


@app.get("/api/positions")
async def get_positions():
    scheduler = _state.get("scheduler")
    if not scheduler:
        return {"ok": False, "error": "scheduler not initialized"}
    try:
        positions = await scheduler.mcp.get_open_positions()
        return {"ok": True, "positions": positions}
    except Exception as e:
        log_event(log, "api_positions_error", {"error": str(e)})
        return {"ok": False, "error": str(e), "positions": []}


@app.post("/api/positions/{position_id}/close")
async def close_position(position_id: str):
    scheduler = _state.get("scheduler")
    if not scheduler:
        return {"ok": False, "error": "scheduler not initialized"}
    log_event(log, "api_close_position", {"position_id": position_id})
    try:
        result = await scheduler.mcp.close_position(position_id)
        await scheduler.on_event("log", {
            "message": f"Position {position_id} closed via API",
        })
        # Refresh positions on frontend
        positions = await scheduler.mcp.get_open_positions()
        await scheduler.on_event("positions_update", {"positions": positions})
        return {"ok": True, "result": result, "positions": positions}
    except Exception as e:
        log_event(log, "api_close_position_error", {
            "position_id": position_id,
            "error": str(e),
        })
        return {"ok": False, "error": str(e)}


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
