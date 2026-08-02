"""Thin wrapper around the cTrader MCP server. This is the ONLY module
allowed to place/modify/cancel real trades — keep it small and well-tested.

Uses AsyncExitStack for async lifecycle management, dynamic tool discovery
via list_tools(), and a TOOL_NAMES mapping for logical-to-actual tool name
resolution with automatic fallback matching.

Author: Inventions4All - github:TWeb79
Version: 1.2.0  (deployment: 2026-08-02)
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .logger import get_logger, log_event

log = get_logger("chartwatch.mcp")

TOOL_NAMES = {
    "get_positions": "get_positions",
    "open_position": "open_position",
    "close_position": "close_position",
    "modify_position": "modify_position",
}

_TOOL_ALIASES = {
    "get_positions": ["get_positions", "list_positions", "positions", "GetPositions"],
    "open_position": ["open_position", "create_position", "OpenPosition", "PlaceOrder"],
    "close_position": ["close_position", "ClosePosition", "CloseTrade"],
    "modify_position": ["modify_position", "modify_sl", "ModifyPosition", "ModifyTrade"],
}


def _find_tool_name(logical_name: str, available_tools: dict[str, Any]) -> str | None:
    """Resolve a logical tool name to the actual server tool name.

    Tries, in order:
    1. Exact match in TOOL_NAMES
    2. Exact match in available_tools
    3. Case-insensitive match
    4. Partial/substring match
    5. Description keyword match
    """
    if logical_name in available_tools:
        return logical_name

    candidates = _TOOL_ALIASES.get(logical_name, [logical_name])
    available_lower = {k.lower(): k for k in available_tools}

    for candidate in candidates:
        if candidate in available_tools:
            return candidate
        if candidate.lower() in available_lower:
            return available_lower[candidate.lower()]

    for avail_name in available_tools:
        avail_lower = avail_name.lower()
        for candidate in candidates:
            candidate_lower = candidate.lower()
            if (avail_lower.startswith(candidate_lower) or
                avail_lower.endswith(candidate_lower) or
                candidate_lower.startswith(avail_lower) or
                candidate_lower.endswith(avail_lower)):
                return avail_name

    for avail_name, tool in available_tools.items():
        desc = (tool.description or "").lower()
        for candidate in candidates:
            if candidate.lower() in desc:
                return avail_name

    return None


def _extract_text(result: Any) -> str:
    """Extract concatenated text from MCP CallToolResult content blocks."""
    parts = []
    for c in result.content:
        if hasattr(c, "text"):
            parts.append(c.text)
        elif isinstance(c, dict):
            parts.append(c.get("text", ""))
        elif isinstance(c, str):
            parts.append(c)
    return "\n".join(parts)


def _parse_json_text(text: str) -> Any:
    """Parse JSON from the first JSON object/array found in text."""
    text = text.strip()
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])
    raise ValueError(f"no JSON object or array found in: {text!r}")


class CTraderMCPClient:
    """Thin wrapper around an MCP ClientSession talking to the cTrader MCP server."""

    def __init__(self, url: str, account_id: int | None = None) -> None:
        self.url = url
        self.account_id = account_id
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None
        self.available_tools: dict[str, Any] = {}
        self._resolved_tools: dict[str, str] = {}

    async def connect(self) -> None:
        """Connect to the cTrader MCP server and discover available tools."""
        if self.session is not None:
            try:
                await self.disconnect()
            except Exception:
                pass
        log_event(log, "mcp_connect_start", {"url": self.url})
        read, write = await self._stack.enter_async_context(
            streamable_http_client(self.url),
        )
        self.session = await self._stack.enter_async_context(
            ClientSession(read, write),
        )
        await self.session.initialize()

        tools_result = await self.session.list_tools()
        self.available_tools = {t.name: t for t in tools_result.tools}
        self._resolved_tools: dict[str, str] = {}
        for logical_name in TOOL_NAMES:
            resolved = _find_tool_name(logical_name, self.available_tools)
            if resolved:
                self._resolved_tools[logical_name] = resolved
        log_event(log, "mcp_connect_ok", {
            "url": self.url,
            "tools": list(self.available_tools.keys()),
            "resolved": self._resolved_tools,
        })
        if not self.available_tools:
            log.warning(
                "cTrader MCP server at %s returned no tools. "
                "Verify the server is running and properly configured.",
                self.url,
            )
        else:
            log.info("Connected to cTrader MCP server. Available tools:")
            for name, tool in self.available_tools.items():
                desc = (tool.description or "").strip().replace("\n", " ")[:100]
                log.info("  - %s: %s", name, desc)
            unresolved = [k for k in TOOL_NAMES if k not in self._resolved_tools]
            if unresolved:
                log.warning(
                    "Could not resolve logical tool names: %s. "
                    "Available tools: %s. "
                    "Update TOOL_NAMES or _TOOL_ALIASES to match your server.",
                    unresolved,
                    list(self.available_tools.keys()),
                )

    async def _ensure_connected(self) -> bool:
        """Ensure the MCP session is connected, reconnecting if needed.

        Returns True if the session is active, False if connection failed.
        """
        if self.session is not None:
            return True
        try:
            await self.connect()
            return self.session is not None
        except Exception as e:
            log_event(log, "mcp_connect_failed", {"error": str(e)})
            return False

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the cTrader MCP server.

        Args:
            tool_name: Logical tool name (mapped via TOOL_NAMES / _resolved_tools).
            arguments: Dict of arguments for the tool call.

        Returns:
            Parsed tool result (dict or list).

        Raises:
            RuntimeError: If the tool is not available on the server.
            ConnectionError: If the MCP session is not connected and cannot connect.
        """
        if not await self._ensure_connected():
            raise ConnectionError("MCP session not connected and auto-connect failed")
        actual_name = self._resolved_tools.get(tool_name)
        if actual_name is None:
            actual_name = _find_tool_name(tool_name, self.available_tools)
        if actual_name is None:
            log_event(log, "mcp_call_error", {
                "tool": tool_name,
                "error": "tool not found",
                "available": list(self.available_tools.keys()),
            })
            raise RuntimeError(
                f"Tool '{tool_name}' not found. "
                f"Available: {list(self.available_tools.keys())}. "
                "Update TOOL_NAMES or _TOOL_ALIASES to match your server."
            )
        log_event(log, "mcp_call", {"tool": actual_name, "arguments": arguments})
        if actual_name not in self.available_tools:
            log_event(log, "mcp_call_error", {
                "tool": actual_name,
                "error": "tool not found",
                "available": list(self.available_tools.keys()),
            })
            raise RuntimeError(
                f"Tool '{actual_name}' not found. "
                f"Available: {list(self.available_tools.keys())}."
            )
        result = await self.session.call_tool(actual_name, arguments)
        log_event(log, "mcp_response", {"tool": actual_name, "status": "ok"})
        for block in result.content:
            if hasattr(block, "text"):
                try:
                    return json.loads(block.text)
                except (json.JSONDecodeError, TypeError):
                    raise RuntimeError(
                        f"Tool '{actual_name}' returned non-JSON text: {block.text!r}"
                    )
        raise RuntimeError(
            f"Tool '{actual_name}' returned no text content in result blocks"
        )

    async def get_open_positions(self) -> list[dict[str, Any]]:
        """Fetch open positions from the cTrader MCP server."""
        raw = await self.call(TOOL_NAMES["get_positions"], {})
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            return [raw]
        return []

    async def open_position(
        self, symbol: str, direction: str, volume: float, sl: float, tp: float
    ) -> dict[str, Any]:
        """Open a new position on the cTrader MCP server."""
        return await self.call(TOOL_NAMES["open_position"], {
            "symbol": symbol,
            "direction": direction,
            "volume": volume,
            "stop_loss": sl,
            "take_profit": tp,
        })

    async def close_position(self, position_id: str) -> dict[str, Any]:
        """Close an existing position on the cTrader MCP server."""
        return await self.call(TOOL_NAMES["close_position"], {
            "position_id": position_id,
        })

    async def modify_sl(self, position_id: str, new_sl: float) -> dict[str, Any]:
        """Modify the stop-loss of an existing position."""
        return await self.call(TOOL_NAMES["modify_position"], {
            "position_id": position_id,
            "stop_loss": new_sl,
        })

    async def close(self) -> None:
        """Close the MCP connection."""
        await self._stack.aclose()

    async def verify(self) -> dict[str, Any]:
        """Probe the MCP endpoint and return diagnostic info without fully connecting.

        The MCP server uses Streamable HTTP transport — a plain GET returns
        HTTP 400 (Bad Request) because it expects MCP protocol messages.
        A 400 response means the server is running, so we treat any HTTP
        response as reachable.
        """
        import urllib.error
        result = {"url": self.url, "reachable": False, "status": None, "tools": []}
        try:
            req = urllib.request.Request(self.url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                result["reachable"] = True
                result["status"] = resp.status
        except urllib.error.HTTPError as e:
            # HTTP 400 from MCP server is expected for plain GET — server is running
            result["reachable"] = True
            result["status"] = e.code
        except Exception as e:
            result["error"] = str(e)
        return result

    async def get_accounts(self) -> list[dict[str, Any]]:
        """Fetch all available cTrader accounts.

        Ensures the MCP session is connected before calling tools.
        Returns an empty list if the connection cannot be established.
        """
        if not await self._ensure_connected():
            return []
        raw = await self.call("get_accounts_list", {})
        if isinstance(raw, dict):
            return raw.get("accounts", [])
        return []

    async def get_account_balance(self) -> dict[str, Any]:
        """Fetch the balance for the configured account_id.

        Looks up the account in the accounts list returned by
        ``get_accounts_list`` and returns its embedded ``balance`` field.
        Falls back to a separate ``get_balance`` tool call if the account
        is not found in the list or has no balance field.

        Returns:
            Dict with ``balance`` (float | None), ``currency`` (str | None),
            and ``account_id`` (int | None). Returns ``balance=None`` if
            the MCP connection cannot be established.
        """
        result: dict[str, Any] = {
            "account_id": self.account_id,
            "balance": None,
            "currency": None,
        }
        if self.account_id is None:
            return result
        try:
            accounts = await self.get_accounts()
            selected = next(
                (a for a in accounts if a.get("id") == self.account_id), None
            )
            if selected and selected.get("balance") is not None:
                result["balance"] = float(selected["balance"])
                result["currency"] = selected.get("currency")
                log_event(log, "mcp_balance_from_list", {
                    "account_id": self.account_id,
                    "balance": result["balance"],
                    "currency": result["currency"],
                })
                return result
            # Fallback: call get_balance explicitly
            balance_result = await self.call("get_balance", {})
            if isinstance(balance_result, dict) and balance_result.get("balance") is not None:
                result["balance"] = float(balance_result["balance"])
                result["currency"] = balance_result.get("currency")
                log_event(log, "mcp_balance_from_tool", {
                    "account_id": self.account_id,
                    "balance": result["balance"],
                })
        except Exception as e:
            log_event(log, "mcp_balance_error", {
                "account_id": self.account_id,
                "error": str(e),
            })
        return result

    async def verify_account(self) -> dict[str, Any]:
        """Verify the active cTrader account matches the expected account_id.

        Returns a dict with 'match' (bool), 'active_login', 'active_id',
        and 'expected_login' / 'expected_id' for diagnostics.
        """
        if self.account_id is None:
            return {"match": False, "error": "no account_id configured"}
        try:
            accounts = await self.call("get_accounts_list", {})
            account_list = accounts.get("accounts", []) if isinstance(accounts, dict) else []
            for acc in account_list:
                if acc.get("id") == self.account_id:
                    balance = await self.call("get_balance", {})
                    return {
                        "match": True,
                        "active_id": acc["id"],
                        "active_login": acc.get("login"),
                        "active_balance": balance.get("balance"),
                        "expected_id": self.account_id,
                    }
            return {
                "match": False,
                "error": f"account_id {self.account_id} not found in active accounts",
                "available": [{"id": a["id"], "login": a.get("login")} for a in account_list],
            }
        except Exception as e:
            return {"match": False, "error": str(e)}

    async def disconnect(self) -> None:
        """Disconnect and reset state for reconnection."""
        await self.close()
        self._stack = AsyncExitStack()
        self.session = None
        self.available_tools = {}
        self._resolved_tools = {}