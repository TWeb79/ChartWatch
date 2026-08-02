# Implementation Plan

## Bug Fix: Client.chat() got an unexpected keyword argument 'timeout'

### Problem
`chartwatch/ollama_client.py` passed `timeout=120.0` as a keyword argument
to `ollama.Client.chat()`, which does not accept it. This caused a runtime
`TypeError` during every analysis cycle, preventing the LLM from being
called.

### Root Cause
The `ollama` Python library (v0.3.3) accepts `timeout` on the
`ollama.Client()` constructor (forwarded to the underlying `httpx.Client`),
not on the `.chat()` method. The `timeout` kwarg was incorrectly placed on
the `chat()` call instead of the `Client()` constructor.

### Fix
1. Move `timeout=120.0` from `client.chat(...)` to `ollama.Client(host=host, timeout=120.0)`.
2. Remove `timeout=120.0` from the `client.chat(...)` call.

### Tests Added
- `TestOllamaClientAnalyze.test_analyze_returns_dict` — verifies JSON parsing works.
- `TestOllamaClientAnalyze.test_analyze_passes_timeout_to_client_constructor_not_chat` —
  regression test asserting `timeout` goes to `Client()` constructor and NOT to `chat()`.
- `TestOllamaClientAnalyze.test_analyze_raises_on_empty_response` — empty response raises ValueError.
- `TestOllamaClientAnalyze.test_analyze_raises_on_invalid_json` — malformed JSON raises ValueError.

### Status
Complete.

---

## Task 1: LLM Status Icon in Header

Add a status badge showing the configured LLM provider (Ollama/NVIDIA) and whether it is reachable.

### Backend (`api.py`)
- Added `GET /api/health/llm` endpoint that checks the configured provider:
  - For "ollama": probes `http://localhost:11434/api/tags` (configurable host)
  - For "nvidia": probes `https://integrate.api.nvidia.com/v1/models` with the configured API key
  - Returns `{"provider": "ollama"|"nvidia", "model": str, "reachable": bool, "error": str|None}`

### Frontend
- `index.html`: Added `#llm-status` badge alongside WS/cTrader/MCP badges
- `app.js`: Added `fetchLlmHealth()` and `updateLlmStatus()` functions;
  called on startup and refreshed every 60s

### Tests Added
- `TestLlmHealthEndpoint.test_ollama_provider_returns_structure` — Ollama reachable
- `TestLlmHealthEndpoint.test_ollama_unreachable` — Ollama unreachable
- `TestLlmHealthEndpoint.test_nvidia_provider_returns_structure` — NVIDIA reachable

### Status
Complete.

---

## Task 2: Account Limits / Balance Refresh Timing

Change when account + balance information is fetched:
1. **On startup**: fetch accounts once (via `fetchSystemStatus()`)
2. **On MCP status click**: fetch accounts (via `fetchMcpAccounts()`)
3. **On screenshot take / cycle start**: trigger `fetchMcpAccounts()` via the WS `"capture"` event handler

### Changes
- `app.js`: Replaced `setInterval(fetchSystemStatus, 30000)` with `fetchLlmHealth()` + `setInterval(fetchLlmHealth, 60000)` — LLM health is checked periodically, accounts are checked on startup/click/capture
- `app.js`: Added `fetchMcpAccounts()` call in the `"capture"` WS event handler to refresh balance after screenshot

### Status
Complete.

---

## All Tests
72 tests pass (68 original + 3 new LLM health endpoint tests + 1 new account balance fallback test).

---

## Bug Fix: Wrong account balance returned

### Problem
When the user selected a demo account with 1000 EUR balance, the system
showed 166.24 — the balance of whatever cTrader account was currently
active, not the selected ChartWatch account.

### Root Cause
In `chartwatch/api.py`, the `mcp_accounts()` endpoint called
`scheduler.mcp.call("get_balance", {})` with empty arguments. The MCP
`get_balance` tool does not receive the `account_id`, so it returns the
balance of the currently active cTrader account — which may differ from
the account the user selected in ChartWatch.

### Fix
The `get_accounts()` call already returns accounts with their `balance`
fields. The endpoint now:
1. Finds the selected account in the accounts list and uses its `balance`
2. Falls back to `get_balance` only if the selected account is not found
   in the accounts list

### Tests Updated/Added
- `TestMcpAccountsEndpoint.test_accounts_returns_structure` — updated to
  assert `selectedBalance == 1000.0` (from accounts list) and that
  `get_balance` is NOT called
- `TestMcpAccountsEndpoint.test_accounts_fallback_to_get_balance_when_not_in_list`
  — new test for the fallback path

### Status
Complete.
