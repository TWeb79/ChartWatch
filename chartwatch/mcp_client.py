"""Thin wrapper around the cTrader MCP server. This is the ONLY module
allowed to place/modify/close real trades — keep it small and well-tested.

TODO: confirm the exact tool names/parameters the server exposes (call
list_tools() once connected and adjust the calls below to match — tool
names below are best-guess placeholders based on common MCP trading
server conventions).
"""

from __future__ import annotations
import json
from typing import Any
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


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
    def __init__(self, url: str):
        self.url = url

    @asynccontextmanager
    async def _session(self):
        async with streamable_http_client(self.url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def list_tools(self) -> list[str]:
        async with self._session() as session:
            tools = await session.list_tools()
            return [t.name for t in tools.tools]

    async def get_open_positions(self) -> list[dict[str, Any]]:
        async with self._session() as session:
            result = await session.call_tool("get_positions", {})
            text = _extract_text(result)
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return []
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
            return []

    async def open_position(
        self, symbol: str, direction: str, volume: float, sl: float, tp: float
    ) -> dict[str, Any]:
        async with self._session() as session:
            result = await session.call_tool(
                "open_position",
                {
                    "symbol": symbol,
                    "direction": direction,  # "buy" | "sell"
                    "volume": volume,
                    "stop_loss": sl,
                    "take_profit": tp,
                },
            )
            text = _extract_text(result)
            try:
                return _parse_json_text(text)
            except (json.JSONDecodeError, ValueError):
                return {"raw": text}

    async def close_position(self, position_id: str) -> dict[str, Any]:
        async with self._session() as session:
            result = await session.call_tool(
                "close_position", {"position_id": position_id}
            )
            text = _extract_text(result)
            try:
                return _parse_json_text(text)
            except (json.JSONDecodeError, ValueError):
                return {"raw": text}

    async def modify_sl(self, position_id: str, new_sl: float) -> dict[str, Any]:
        async with self._session() as session:
            result = await session.call_tool(
                "modify_position",
                {"position_id": position_id, "stop_loss": new_sl},
            )
            text = _extract_text(result)
            try:
                return _parse_json_text(text)
            except (json.JSONDecodeError, ValueError):
                return {"raw": text}
