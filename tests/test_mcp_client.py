"""Tests for the cTrader MCP client price lookup behavior."""

from unittest.mock import AsyncMock

import pytest

from chartwatch.mcp_client import CTraderMCPClient


@pytest.mark.asyncio
async def test_get_symbol_price_uses_symbol_name_for_spot_tool(monkeypatch):
    client = CTraderMCPClient("http://example.test")
    client._resolved_tools = {"get_symbol_price": "get_spot_prices"}
    monkeypatch.setattr(client, "_ensure_connected", AsyncMock(return_value=True))
    client.call = AsyncMock(return_value={"ask": 123.45})

    price = await client.get_symbol_price("US500")

    assert price == 123.45
    client.call.assert_awaited_once_with("get_symbol_price", {"symbolName": "US500"})
