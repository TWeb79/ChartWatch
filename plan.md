# ChartWatch — Pending Actions & Bug Fixes

## Completed Fixes

### Critical Bugs

1. **MCP client returns raw content blocks instead of parsed data** — `chartwatch/mcp_client.py`
   - Added `_extract_text()` helper to join `.text` from MCP content blocks
   - Added `_parse_json_text()` to extract and parse JSON from text
   - All four methods (`get_open_positions`, `open_position`, `close_position`, `modify_sl`) now return parsed data instead of raw content lists

2. **`PendingApproval.resolve()` not thread-safe** — `chartwatch/scheduler.py`
   - `PendingApproval` now receives the event loop reference and uses `loop.call_soon_threadsafe(event.set)` instead of `event.set()`
   - Manual approval/denial now correctly wakes the scheduler's `wait_for()`

3. **Blocking Ollama call in async event loop** — `chartwatch/scheduler.py`
   - `ollama_client.analyze()` now wrapped in `asyncio.to_thread()` so it runs in a threadpool
   - Event loop stays responsive for WebSocket keepalive and HTTP API requests

4. **WebSocket `_ws_clients.remove()` race condition** — `chartwatch/api.py`
   - Added `asyncio.Lock` (`_ws_lock`) to protect `_ws_clients`
   - `_broadcast` and `ws_endpoint` both acquire the lock for list mutations
   - `_ws_clients.remove()` guarded with `try/except ValueError`

5. **SQLite connection shared across threads without locking** — `chartwatch/storage.py`
   - Added `threading.Lock` to `Storage`
   - All `execute`/`commit` calls go through `_execute()` which acquires the lock
   - Added `daily_pnl_pct()` method to compute today's PnL from history

### MCP Transport Fix

6. **MCP transport changed from SSE to Streamable HTTP** — `chartwatch/mcp_client.py`
   - cTrader MCP server is configured as `"type": "http"` in the MCP config, not SSE
   - Changed from `mcp.client.sse.sse_client` to `mcp.client.streamable_http.streamable_http_client`
   - Updated `config.yaml` URL to `http://127.0.0.1:9876/mcp/` and server port to `8056`

### Important Improvements

7. **Symbol fallback to `"UNKNOWN"`** — `chartwatch/scheduler.py` + `config.yaml`
   - Added `trading.default_symbol` config field (default: `"EURUSD"`)
   - `_execute()` now uses `default_symbol` when no position context is available

8. **`daily_pnl_pct` stubbed to `0.0`** — `chartwatch/scheduler.py` + `chartwatch/storage.py`
   - `Storage.daily_pnl_pct()` computes today's realized PnL from the cycles table
   - Guardrail now receives actual computed value instead of hardcoded `0.0`

9. **`pip_size` hardcoded to 0.0001** — `chartwatch/guardrails.py` + `config.yaml`
   - `guardrails.check()` now accepts a `pip_size` parameter (default: `0.0001`)
   - Added `trading.pip_size` config field
   - Scheduler passes `pip_size` from config to `guardrails.check()`

### Minor Fixes

10. **JS countdown desynced from server timeout** — `static/app.js`
    - Added handler for `auto_denied_timeout` WebSocket event that calls `hideApproval()`

11. **No WebSocket reconnect** — `static/app.js`
    - Added `connectWs()` function with `onclose` handler that reconnects after 3 seconds
    - `onerror` triggers `ws.close()` to fire the reconnect logic

12. **`_broadcast` catches all exceptions** — `chartwatch/api.py`
    - Already narrowed as part of bug #4 fix (lock-protected removal, ValueError guard)

13. **History rows use client-local time** — `static/app.js`
    - History rows now use `row.ts` (server timestamp) converted via `new Date(row.ts * 1000)`

---

### Window Selection Bug

8. **`app_selector.py` `title` check filtered out all application windows** — `chartwatch/app_selector.py`
   - Removed the `and title` check that required `kCGWindowName` to be non-empty. Many macOS apps (VS Code, Safari, Finder, etc.) report empty window titles through Quartz, so this check incorrectly filtered out ALL valid application windows
   - Added `_SYSTEM_WINDOW_OWNERS` exclude list (with English and German names for system processes like Control Center/Notification Center) to replace the `layer == 0` check, which is more reliable than layer numbers and locale-independent via owner names
   - Removed the `layer` variable entirely

### New Features

9. **Scheduler start/stop control** — `chartwatch/scheduler.py` + `chartwatch/api.py` + `static/app.js` + `static/index.html` + `static/style.css`
   - Added `trigger_cycle()` method on `Scheduler` for manual single-cycle execution
   - Added `POST /api/scheduler/start` and `POST /api/scheduler/stop` endpoints
   - Added Start/Stop buttons in the frontend UI with status indicator
   - Added Log section showing cycle progress in real-time
   - Added Ollama Response section displaying the raw model output

10. **Cycle step logging via WebSocket** — `chartwatch/scheduler.py` + `static/app.js`
    - Added `cycle_start`, `log`, and `model_response` WebSocket event types at each pipeline stage
    - Frontend logs show: cycle start, screenshot captured & stored, Ollama submission, Ollama response received

## Remaining TODOs (not actionable without external setup)

- **`mcp_client.py` tool names** — best-guess placeholders; call `list_tools()` against the real cTrader MCP server once connected
- **`guardrails.py` SL-distance guardrail** — `current_price` is still `None` because no MCP quote tool is wired; the check is silently skipped
- **`app_selector.py`** — `Quartz` module has no type stubs (macOS-specific, expected mypy warning)