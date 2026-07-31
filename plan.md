# ChartWatch — Remaining TODOs

## MCP Connection

- **`mcp_client.py` tool names** — best-guess placeholders; call `list_tools()` against the real cTrader MCP server once connected. The cTrader MCP server is running on port 9876 but does not currently expose standard MCP protocol endpoints (`/mcp/`, `/sse`, `/streamable` all return 404). The server may use a non-standard path or require additional configuration. See the inline TODO in `mcp_client.py` for the verification script and troubleshooting steps.

## Not Actionable Without External Setup

- **`guardrails.py` SL-distance guardrail** — `current_price` is still `None` because no MCP quote tool is wired; the check is silently skipped
- **`app_selector.py`** — `Quartz` module has no type stubs (macOS-specific, expected mypy warning)
