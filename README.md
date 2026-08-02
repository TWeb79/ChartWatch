# ChartWatch
by Inventions4All - github:TWeb79 - Version 2026-08-02 (deployment: 2026-08-02T11:42)


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
    Open **http://localhost:8056** — pick the target window, set the
    interval, and leave auto-approve off until you trust the pipeline.

## Using the NVIDIA Provider (Optional)

ChartWatch supports NVIDIA's hosted API as an alternative to a local Ollama
instance. To use it:

1. **Obtain a free API key** at https://build.nvidia.com/models
   - Sign in with a free NVIDIA Developer account
   - Navigate to the **API** tab
   - Create a new API key
   - Copy the key

2. **Add the key to `config.yaml`:**
   ```yaml
   provider: nvidia
   nvidia:
     api_key: "YOUR_NVIDIA_API_KEY_HERE"
     base_url: "https://integrate.api.nvidia.com/v1"
     model: "meta/llama-3.3-70b-instruct"
   ```
   Free vision-capable models include `meta/llama-3.3-70b-instruct`,
   `google/gemma-3-27b-it`, and `nvidia/nemotron-vl-340b`.

3. **Startup behavior:** On first launch the app fetches the model list from
   the configured provider, filters to only free vision-capable models, and
   caches the result in `<provider>_models.json` in the repository root.
   On subsequent startups the cached list is used directly. The LLM status
   badge shows "Analyzing models..." (yellow) while the test runs. Click the
   status badge to manually refresh the model list.

**Switching providers:** To return to Ollama, set `provider: ollama` in
`config.yaml` and ensure Ollama is running locally.

## Known TODOs (marked in code)

- `chartwatch/mcp_client.py`: tool names are heuristically resolved from the
  MCP server tool list. If `get_accounts_list` or other account/position tools
  are not found, update `_TOOL_ALIASES` to match your server's exact names.
- `chartwatch/guardrails.py`: pip-size conversion is hardcoded for a
  4-decimal FX pair and may need per-symbol handling for non-FX instruments.
- `chartwatch/scheduler.py`: `daily_pnl_pct` and current symbol price are now
  wired to actual MCP data when available, but additional quote sources may be
  needed for non-standard symbols.

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

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/windows` | List available macOS windows for target selection |
| POST | `/api/config/target-window` | Set target window by ID and title |
| POST | `/api/config/interval` | Set polling interval in minutes |
| POST | `/api/config/auto-approve` | Toggle auto-approve trades |
| POST | `/api/config` | Patch arbitrary config keys (merge) |
| POST | `/api/config/ctrader-account` | Set active cTrader `account_id` |
| GET | `/api/mcp/accounts` | Fetch all cTrader accounts + selected balance |
| GET | `/api/mcp/verify` | Probe MCP server reachability |
| GET | `/api/health` | Check MCP + Ollama health |
| GET | `/api/health/llm` | Check configured LLM provider (Ollama/NVIDIA) reachability |
| GET | `/api/llm/models` | List filtered (vision-capable, free) models for the configured provider |
| GET | `/api/llm/models/test` | Re-run the model availability + vision test and refresh the cache |
| GET | `/api/health/prerequisites` | Check cTrader process + MCP reachability |
| GET | `/api/history` | Fetch recent cycle history |
| GET | `/api/scheduler/timing` | Get interval timing info |
| POST | `/api/scheduler/start` | Trigger a single cycle immediately |
| POST | `/api/scheduler/stop` | Stop the scheduler loop |
| POST | `/api/approve/{cycle_id}` | Approve a pending trade proposal |
| POST | `/api/deny/{cycle_id}` | Deny a pending trade proposal |
| WS | `/ws` | Real-time events (cycle start, log, model response, etc.) |

### Account selector

Click the MCP status badge in the header to open an account dropdown.
Select an account to persist it via `POST /api/config/ctrader-account`.
The Settings page also has a cTrader Account selector under Configuration.
