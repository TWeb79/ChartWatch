"""Thin wrapper around the cTrader MCP server. This is the ONLY module
allowed to place/modify/cancel real trades — keep it small and well-tested.

Uses AsyncExitStack for async lifecycle management, dynamic tool discovery
via list_tools(), and a TOOL_NAMES mapping for logical-to-actual tool name
resolution.

Author: Inventions4All - github:TWeb79
Version: 1.0.0  (deployment: 2026-07-31)
"""

from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

log = logging.getLogger("ai_trader.mcp")

TOOL_NAMES = {
    "get_positions": "get_positions",
    "open_position": "open_position",
    "close_position": "close_position",
    "modify_position": "modify_position",
}


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

    def __init__(self, url: str) -> None:
        self.url = url
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None
        self.available_tools: dict[str, Any] = {}

    async def connect(self) -> None:
        """Connect to the cTrader MCP server and discover available tools."""
        read, write = await self._stack.enter_async_context(
            streamable_http_client(self.url),
        )
        self.session = await self._stack.enter_async_context(
            ClientSession(read, write),
        )
        await self.session.initialize()

        tools_result = await self.session.list_tools()
        self.available_tools = {t.name: t for t in tools_result.tools}
        log.info("Connected to cTrader MCP server. Available tools:")
        for name, tool in self.available_tools.items():
            desc = (tool.description or "").strip().replace("\n", " ")[:100]
            log.info("  - %s: %s", name, desc)

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the cTrader MCP server.

        Args:
            tool_name: Logical tool name (mapped via TOOL_NAMES).
            arguments: Dict of arguments for the tool call.

        Returns:
            Parsed tool result (dict or list).

        Raises:
            RuntimeError: If the tool is not available on the server.
        """
        if tool_name not in self.available_tools:
            raise RuntimeError(
                f"Tool '{tool_name}' not found. "
                f"Available: {list(self.available_tools.keys())}. "
                "Update TOOL_NAMES to match your server.",
            )
        result = await self.session.call_tool(tool_name, arguments)
        for block in result.content:
            if hasattr(block, "text"):
                try:
                    return json.loads(block.text)
                except (json.JSONDecodeError, TypeError):
                    return block.text
        return result

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