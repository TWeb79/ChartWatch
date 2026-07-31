# ChartWatch — Remaining TODOs

## Critical Bugs

- None remaining

## MCP Connection

- **`mcp_client.py` tool names** — best-guess placeholders; call `list_tools()` against the real cTrader MCP server once connected. The cTrader MCP server is running on port 9876 but does not currently expose standard MCP protocol endpoints (`/mcp/`, `/sse`, `/streamable` all return 404). The server may use a non-standard path or require additional configuration. See the inline TODO in `mcp_client.py` for the verification script and troubleshooting steps.

## Not Actionable Without External Setup

- **`guardrails.py` SL-distance guardrail** — `current_price` is still `None` because no MCP quote tool is wired; the check is silently skipped
- **`app_selector.py`** — `Quartz` module has no type stubs (macOS-specific, expected mypy warning)

## Completed Tasks

- **UI Enhancements**:
  - Unified expand/collapse interface using arrow symbols (▶/▼) across all collapsible elements
  - Enhanced history table with expandable rows showing detailed information (screenshots, assessments, trade details, guardrail status, MCP results)
  - Improved history sorting to display newest entries first (ordered by timestamp) — fixed `prepend` → `append` in app.js
  - Fixed static file path references (removed incorrect "/static/" prefix)
  - Standardized Ollama response expand/collapse button to use arrow symbols
  - Fixed indentation issues in storage.py
  - Added `/screenshots` static mount in api.py for screenshot preview

- **Error Handling Improvements**:
  - Added empty response detection in Ollama client to prevent JSON parse errors
  - Added warning when MCP server connects but returns no tools
  - Wrapped Ollama API calls in scheduler with try/catch to prevent cycle crashes
  - Enhanced MCP client logging to warn when server returns no tools

- **Code Quality**:
  - Removed duplicate logger initialization in mcp_client.py
