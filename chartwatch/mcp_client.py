"""Thin wrapper around the cTrader MCP server. This is the ONLY module
allowed to place/modify/cancel real trades — keep it small and well-tested.

Uses AsyncExitStack for async lifecycle management, dynamic tool discovery
via list_tools(), and a TOOL_NAMES mapping for logical-to-actual tool name
resolution with automatic fallback matching.

Author: Inventions4All - github:TWeb79
Version: 1.2.0  (deployment: 2026-08-02)
"""

from __future__ import annotations

import asyncio
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
    "get_balance": "get_balance",
    "get_symbol_price": "get_symbol_price",
    "get_account_statistics": "get_account_statistics",
    "get_deals": "get_deals",
    "get_order_history": "get_order_history",
}

_TOOL_ALIASES = {
    "get_positions": ["get_positions", "list_positions", "positions", "GetPositions"],
    "open_position": [
        "open_position", "create_position", "OpenPosition", "PlaceOrder",
        "place_market_order", "PlaceMarketOrder",
    ],
    "close_position": [
        "close_position", "ClosePosition", "CloseTrade", "close_position_partial",
    ],
    "modify_position": [
        "modify_position", "modify_sl", "ModifyPosition", "ModifyTrade",
        "amend_position", "AmendPosition", "amend_order",
    ],
    "get_balance": ["get_balance", "getAccountBalance", "GetBalance", "get_account_statistics"],
    "get_symbol_price": [
        "get_symbol_price", "get_symbol_prices", "get_prices", "getQuotes",
        "get_quote", "GetSymbolPrice", "SymbolPrice", "GetPrice",
        "get_spot_prices", "GetSpotPrices",
    ],
    "get_account_statistics": [
        "get_account_statistics", "getAccountStatistics", "get_stats",
        "get_account_info", "GetAccountInfo",
    ],
    "get_deals": [
        "get_deals", "getDealHistory", "GetDeals", "deal_history",
        "get_closed_positions", "closed_positions",
    ],
    "get_order_history": [
        "get_order_history", "getOrderHistory", "GetOrders",
        "order_history", "orders",
    ],
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


def _filter_by_year(item: dict[str, Any], year_start_ts: float) -> bool:
    """Check if a deal/order/position dict has a timestamp >= year_start_ts.

    Looks for common timestamp field names: ``timestamp``, ``time``,
    ``created``, ``open_time``, ``close_time``, ``date``, ``ts``.
    If no timestamp is found, the item is included (assumed recent).
    """
    for field in ("timestamp", "time", "created", "open_time", "close_time", "date", "ts"):
        val = item.get(field)
        if val is None:
            continue
        try:
            ts = float(val)
            return ts >= year_start_ts
        except (ValueError, TypeError):
            continue
    return True  # No timestamp found — include by default


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
        """Connect to the cTrader MCP server and discover available tools.

        Includes a connection timeout to prevent indefinite hangs when the
        server is unreachable or not responding.
        """
        if self.session is not None:
            try:
                await self.disconnect()
            except Exception as disconnect_err:
                log_event(log, "mcp_disconnect_error", {"error": str(disconnect_err)})
        log_event(log, "mcp_connect_start", {"url": self.url})
        try:
            read, write = await asyncio.wait_for(
                self._stack.enter_async_context(streamable_http_client(self.url)),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            log_event(log, "mcp_connect_timeout", {"url": self.url})
            raise ConnectionError(
                f"MCP server at {self.url} did not respond within 10s — "
                "is cTrader running?"
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

        If the session object exists but the underlying connection may be
        stale (e.g. HTTP connection timed out), attempts a lightweight
        health check via ``call_tool``. If that fails, the session is
        considered dead and a fresh connection is attempted.

        Returns True if the session is active, False if connection failed.
        """
        if self.session is not None:
            # Verify the session is actually alive, not just non-None
            try:
                await asyncio.wait_for(
                    self.session.call_tool("get_server_time", {}),
                    timeout=5.0,
                )
                return True
            except Exception:
                # Session is stale — disconnect and reconnect
                log_event(log, "mcp_session_stale", {})
                try:
                    await self.disconnect()
                except Exception as disconnect_err:
                    log_event(log, "mcp_disconnect_error", {"error": str(disconnect_err)})
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
        result = await asyncio.wait_for(
            self.session.call_tool(actual_name, arguments),
            timeout=30.0,
        )
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

    async def get_free_margin(self) -> float | None:
        """Fetch the free margin for the configured account.

        Tries ``get_account_statistics`` first (cTrader specific), then
        falls back to ``get_balance``. Extracts the ``free_margin`` field
        from either response; falls back to ``equity`` then ``balance``.

        Returns ``None`` if the MCP connection cannot be established.
        """
        if not await self._ensure_connected():
            return None

        # Try get_account_statistics first (cTrader specific, has free_margin)
        try:
            stats_tool = _find_tool_name("get_account_statistics", self.available_tools)
            if stats_tool:
                raw = await self.call("get_account_statistics", {})
                if isinstance(raw, dict):
                    for field in ("free_margin", "equity", "balance"):
                        val = raw.get(field)
                        if val is not None:
                            log_event(log, "mcp_free_margin_from_stats", {
                                "account_id": self.account_id,
                                "field": field,
                                "value": float(val),
                            })
                            return float(val)
        except Exception as e:
            log_event(log, "mcp_stats_error", {
                "account_id": self.account_id,
                "error": str(e),
            })

        # Fallback: use get_balance which returns a dict with balance info
        balance = await self.get_account_balance()
        if balance.get("balance") is None:
            return None
        for field in ("free_margin", "equity", "balance"):
            val = balance.get(field)
            if val is not None:
                log_event(log, "mcp_free_margin_from_balance", {
                    "account_id": self.account_id,
                    "field": field,
                    "value": float(val),
                })
                return float(val)
        return None

    async def get_symbol_price(self, symbol: str) -> float | None:
        """Fetch the current market price of a symbol from the cTrader MCP.

        Handles multiple response formats:
        - ``{"symbol": ..., "ask": ..., "bid": ...}``
        - ``{"price": ...}``
        - ``[{"symbol": ..., "ask": ..., "bid": ...}, ...]`` (list of spot prices)
        - ``{"US500": {"ask": ..., "bid": ...}}`` (dict keyed by symbol)

        Args:
            symbol: The trading symbol (e.g. ``"US500"``, ``"EURUSD"``).

        Returns:
            The current ask price as a float, or ``None`` if the price
            cannot be retrieved.
        """
        if not await self._ensure_connected():
            return None
        raw = await self.call("get_symbol_price", {"symbol": symbol})

        # Format 1: direct dict with ask/bid
        if isinstance(raw, dict):
            if "ask" in raw:
                return float(raw["ask"])
            if "price" in raw:
                return float(raw["price"])
            # Format 3: dict keyed by symbol (from get_spot_prices)
            if symbol in raw and isinstance(raw[symbol], dict):
                price_dict = raw[symbol]
                if "ask" in price_dict:
                    return float(price_dict["ask"])
                if "price" in price_dict:
                    return float(price_dict["price"])

        # Format 2: list of price entries
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict):
                    if entry.get("symbol") == symbol and "ask" in entry:
                        return float(entry["ask"])
                    if entry.get("symbol") == symbol and "price" in entry:
                        return float(entry["price"])

        log_event(log, "mcp_price_not_found", {
            "symbol": symbol,
            "raw": str(raw)[:200],
        })
        return None

    async def get_position_history(self) -> list[dict[str, Any]]:
        """Fetch closed positions (deal history) from the cTrader MCP.

        Tries ``get_deals`` first, then ``get_order_history`` as fallback.
        Filters results to the current year (timestamp >= Jan 1 of current year).
        Returns an empty list if the MCP connection cannot be established
        or no history is available.
        """
        if not await self._ensure_connected():
            return []

        from datetime import datetime
        year_start = datetime.now().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        year_start_ts = year_start.timestamp()

        # Try get_deals first
        try:
            deals_tool = _find_tool_name("get_deals", self.available_tools)
            if deals_tool:
                raw = await self.call("get_deals", {})
                if isinstance(raw, dict):
                    # Could be {"deals": [...]} or {"orders": [...]}
                    items = raw.get("deals") or raw.get("orders") or raw.get("data") or []
                    if isinstance(items, list):
                        return [d for d in items if isinstance(d, dict) and _filter_by_year(d, year_start_ts)]
                if isinstance(raw, list):
                    return [d for d in raw if isinstance(d, dict) and _filter_by_year(d, year_start_ts)]
        except Exception as e:
            log_event(log, "mcp_deals_error", {"error": str(e)})

        # Fallback: get_order_history
        try:
            orders_tool = _find_tool_name("get_order_history", self.available_tools)
            if orders_tool:
                raw = await self.call("get_order_history", {})
                if isinstance(raw, dict):
                    items = raw.get("orders") or raw.get("data") or raw.get("history") or []
                    if isinstance(items, list):
                        return [d for d in items if isinstance(d, dict) and _filter_by_year(d, year_start_ts)]
                if isinstance(raw, list):
                    return [d for d in raw if isinstance(d, dict) and _filter_by_year(d, year_start_ts)]
        except Exception as e:
            log_event(log, "mcp_order_history_error", {"error": str(e)})

        return []

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