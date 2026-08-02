# ChartWatch — Architecture

## Overview

ChartWatch is a macOS desktop application that periodically captures a screenshot of a target application window, sends it to a local Ollama vision model for analysis, and — after approval (manual with a 60s auto-deny timeout, or auto-approve) — executes the resulting trade action via cTrader's local MCP API.

## System Structure

```
ChartWatch/
  main.py                  — Entry point; starts uvicorn with the FastAPI app
  config.yaml              — Runtime configuration (window, interval, Ollama, MCP, trading limits)
  chartwatch/              — Python package (backend)
    api.py                 — FastAPI app: HTTP routes + WebSocket endpoint
    scheduler.py           — Orchestrates capture → analyze → validate → guardrail → approve → execute
    mcp_client.py          — Thin wrapper around cTrader MCP server (Streamable HTTP transport)
    ollama_client.py       — Sends screenshot + context to Ollama vision model, returns parsed decision
    capture.py             — Takes window screenshot via macOS screencapture CLI
    app_selector.py        — Enumerates on-screen windows via Quartz for the UI picker
    storage.py             — SQLite persistence for cycle results
    decision.py            — Validates Ollama response shape before downstream trust
    guardrails.py          — Hard limits enforced regardless of model output
    config.py              — Loads/persists config.yaml
  static/                  — Frontend (served by FastAPI)
    index.html             — Dashboard UI
    app.js                 — Client-side logic (WebSocket, UI updates)
    style.css              — Dashboard styling
  chartwatch.db            — SQLite database (gitignored)
  screenshots/             — Captured window screenshots (gitignored)
```

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `api.py` | FastAPI app; exposes HTTP endpoints for config, scheduler control, history, and a WebSocket for real-time events |
| `scheduler.py` | Core orchestration loop: capture screenshot → call Ollama → validate decision → check guardrails → wait for approval → execute trade via MCP |
| `mcp_client.py` | Communicates with cTrader MCP server using Streamable HTTP transport; provides methods for positions, open/close/modify trades |
| `ollama_client.py` | Sends screenshot + position context to Ollama vision model; forces JSON-only output |
| `capture.py` | Uses macOS `screencapture` CLI to capture a specific window by ID |
| `app_selector.py` | Lists visible windows via Quartz CGWindowList for the UI picker |
| `storage.py` | SQLite-backed persistence with thread-safe access; stores cycle results including model response, guardrail outcome, and action status |
| `decision.py` | Validates the shape and values of the Ollama response dict |
| `guardrails.py` | Enforces hard limits (daily loss, max positions, SL distance, SL/TP direction) |
| `config.py` | Thread-safe load/save/update of `config.yaml` |

## Data Flow

```
User opens dashboard (index.html)
  → WebSocket connects to /ws
  → Scheduler loop runs on startup

Each cycle:
  1. capture.py takes screenshot of target window
  2. Screenshot stored in SQLite + filesystem
  3. ollama_client.py sends screenshot + position context to Ollama
  4. decision.py validates the JSON response shape
  5. guardrails.py checks hard limits (daily loss, concurrent positions, SL distance, SL/TP direction)
  6. If auto_approve: execute immediately; else wait for UI approval (60s timeout)
  7. mcp_client.py executes trade via cTrader MCP
  8. All events broadcast to connected WebSocket clients
  9. Results stored in SQLite
```

Note: The `#log` element (`<pre id="log" class="log-area">`) was restored in
`static/index.html` after it was accidentally removed during a dashboard
redesign. Its absence caused `log()` in `app.js` to throw on every call,
which silently aborted all Start/Stop/WS-log handlers before they could
reach `fetch(...)`. The WebSocket `log` event now has a working UI consumer
again.

## Account Selector

When the application starts, the dashboard fetches all available cTrader
accounts via `GET /api/mcp/accounts` and displays them in a dropdown
accessible from the MCP status badge in the header. Clicking the badge
toggles the account list; clicking an account persists the selection via
`POST /api/config/ctrader-account` (writes `ctrader_mcp.account_id` to
`config.yaml`).

The scheduler re-reads `account_id` from config before each trade execution
(`scheduler.py` `_execute`). The `verify_account()` guard in
`mcp_client.py` checks that the active cTrader session matches the configured
account; if not, trades are aborted with an error event.

## External Dependencies

- **Ollama** — Local LLM vision model (e.g., `qwen3.5:9b`) running at `localhost:11434`
- **cTrader MCP** — Trading platform MCP server at `http://127.0.0.1:9876/mcp/` (Streamable HTTP transport)
- **macOS Quartz** — Window enumeration and screenshot capture (requires Screen Recording permission)
- **FastAPI + uvicorn** — HTTP + WebSocket server
- **SQLite** — Cycle result persistence

## Service Boundaries

- The FastAPI app (`api.py`) is the single entry point for both HTTP and WebSocket traffic
- The scheduler (`scheduler.py`) runs as a background asyncio task created on startup
- The MCP client (`mcp_client.py`) is the only module that places/modifies/cancels real trades
- The storage layer (`storage.py`) is thread-safe and shared across the scheduler and API routes
- The guardrails (`guardrails.py`) are enforced independently of auto_approve and model output

## Port Allocation (per RULES_ports.md)

Project ID 56 → ChartWatch

| Port | Service |
|------|---------|
| 8056 | FastAPI server (web dashboard + API) |
| 8256 | (reserved — database) |
| 8956 | (reserved — LLM) |
