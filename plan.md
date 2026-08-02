# ChartWatch — Bug Fix Plan (Buttons / Countdown / Screenshot Activity)

Author: Inventions4All - github:TWeb79
Created: 2026-08-01

---

## 0. Previously Resolved (see git history)

Status: All items resolved.

| Bug | File(s) | Severity | Status |
|-----|---------|----------|--------|
| Missing `#log` element crashes `log()` | `static/index.html`, `static/app.js` | Critical | Fixed |
| Duplicate `id="history-table"` | `static/index.html`, `static/app.js` | Medium | Fixed |

---

## 1. Resolved

| # | Issue | Status |
|---|-------|--------|
| 1 | Log says "Ollama" when using NVIDIA | Fixed |
| 2 | LLM status goes red with `TypeError: Load failed` | Fixed |
| 3 | Config prompt not used as system prompt | Fixed |
| 4 | No model selection dropdown | Implemented |
| 5 | NVIDIA 500: "multimodal processing is not enabled" | Fixed |

---

## 2. Implemented: Model availability test at startup

| # | Issue | Files | Severity | Status |
|---|-------|-------|----------|--------|
| 6 | Add startup test that probes all models from the selected LLM provider and filters out unavailable / non-vision / paid models | `chartwatch/api.py`, `chartwatch/llm_utils.py`, `tests/test_llm_models.py` | High | Implemented |

### Feature 6 — Model availability + feature test at startup

**Files: `chartwatch/api.py`, `chartwatch/llm_utils.py`, `tests/test_llm_models.py`**

User wants a test that runs once at application startup which:
1. Fetches all available models from the selected LLM provider
2. Tests each model for:
   - Availability (API responds within timeout)
   - Vision/multimodal support (required for screenshot analysis)
   - Free of charge (non-premium)
3. Removes non-qualifying models from the model selection dropdown
4. Caches filtered results to `<provider>_models.json` for subsequent startups
5. Shows yellow "Analyzing models..." status in the LLM badge during testing
6. Uses a 10x10px dummy PNG image and `dummy.md` instructions file for probing

## 3. Resolved Improvements

| # | Issue | Files | Severity | Status |
|---|-------|-------|----------|--------|
| 7 | Scheduler timing endpoint now exposes a minute-based minimum interval, and the UI interval hint updates correctly | `chartwatch/api.py`, `static/app.js` | Medium | Fixed |
| 8 | Guardrails now fetch current symbol price before SL distance evaluation, avoiding skipped validation due to missing price lookup | `chartwatch/scheduler.py`, `chartwatch/mcp_client.py` | High | Fixed |
| 9 | New-trade execution now errors when no valid symbol is configured instead of falling back to `UNKNOWN` | `chartwatch/scheduler.py` | High | Fixed |
| 10 | LLM response rendering uses the existing `.ollama-summary` container directly, preventing unstable nested markup | `static/app.js` | Medium | Fixed |
| 11 | cTrader MCP tool alias mapping now includes `get_accounts_list` for account enumeration | `chartwatch/mcp_client.py` | Medium | Fixed |
| 12 | README and architecture docs were updated for MCP tool discovery, guardrail pricing behavior, and model cache semantics | `README.md`, `ARCHITECTURE.md` | Low | Fixed |


