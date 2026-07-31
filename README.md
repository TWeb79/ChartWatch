# ChartWatch
by Inventions4All - github:TWeb79 - Version 2026-07-31


Periodically screenshots a chosen macOS window (e.g. cTrader), sends it to a
local Ollama vision model for analysis, and — after approval (manual, with a
60s auto-deny timeout, or auto-approve) — executes the resulting trade action
via cTrader's local MCP API.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

1. Pull a vision-capable model in Ollama, e.g.:
   ```bash
   ollama pull qwen3.5:9b
   ```
   Confirm the exact tag matches `ollama.model` in `config.yaml`.

2. Grant **Screen Recording** permission to your terminal / Python
   interpreter: System Settings → Privacy & Security → Screen Recording.
   Without this, window titles and captures come back empty.

3. Fill in `ctrader_mcp.url` in `config.yaml` with the actual local
   endpoint cTrader's MCP API listens on.

4. Run:
   ```bash
   python main.py
   ```
   Open **http://localhost:8765** — pick the target window, set the
   interval, and leave auto-approve off until you trust the pipeline.

## Known TODOs (marked in code)

- `chartwatch/mcp_client.py`: tool names (`open_position`, `close_position`,
  `modify_position`, `get_positions`) are best-guess placeholders — call
  `list_tools()` against the real server once connected and adjust. The cTrader
  MCP server on port 9876 does not currently expose standard MCP protocol
  endpoints; see `mcp_client.py` inline TODO for the verification script.
- `chartwatch/guardrails.py`: pip-size conversion is hardcoded for a
  4-decimal FX pair — needs per-symbol handling for other instrument types.
- `chartwatch/scheduler.py`: `daily_pnl_pct` and `current_price` are stubbed
  to placeholder values — wire these to real MCP quote/history calls.
- Position `symbol` in `_execute()` falls back to `"UNKNOWN"` when no
  position is open — needs a configured default symbol per target window.

## Safety notes

- Guardrails (`risk_limits` in config.yaml) are enforced independently of
  the model's output and independently of `auto_approve` — they cannot be
  bypassed by a confident-sounding model response.
- Every cycle is logged to SQLite (`chartwatch.db`) regardless of outcome —
  useful for reviewing whether the vision model is reading the chart
  correctly before trusting it with auto-approve.
- Strongly recommended: run against a cTrader **demo account** first. A
  local vision model reading a chart screenshot is meaningfully less
  reliable than dedicated market-data-driven trading logic, and errors
  here have real financial consequences.
# ChartWatch
