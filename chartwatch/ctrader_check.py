"""Prerequisite checks for cTrader and the MCP server.

Provides functions to verify that the cTrader application is running
and that the MCP endpoint is reachable before attempting a capture
or analysis cycle.

Author: Inventions4All - github:TWeb79
Version: 1.0.0  (deployment: 2026-08-01)
"""

from __future__ import annotations
import subprocess
import urllib.request
from typing import Any


def check_ctrader_running() -> dict[str, Any]:
    """Check whether the cTrader application process is running on macOS.

    Uses ``pgrep`` to look for a process named ``cTrader``.

    Returns:
        Dict with ``running`` (bool) and ``process_name`` (str).
    """
    try:
        result = subprocess.run(
            ["pgrep", "-x", "cTrader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        running = result.returncode == 0
        return {"running": running, "process_name": "cTrader"}
    except Exception as e:
        return {"running": False, "process_name": "cTrader", "error": str(e)}


def check_mcp_available(url: str, timeout: int = 5) -> dict[str, Any]:
    """Check whether the cTrader MCP server endpoint is reachable.

    Args:
        url: The MCP server URL (e.g. ``http://127.0.0.1:9876/mcp/``).
        timeout: Maximum seconds to wait for a response.

    Returns:
        Dict with ``reachable`` (bool), ``url`` (str), and optional
        ``status`` or ``error`` fields.
    """
    result: dict[str, Any] = {"url": url, "reachable": False}
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result["reachable"] = True
            result["status"] = resp.status
    except Exception as e:
        result["error"] = str(e)
    return result


def check_prerequisites(cfg: dict[str, Any]) -> dict[str, Any]:
    """Run all prerequisite checks and return a combined status.

    Checks:
    1. cTrader process is running.
    2. MCP server endpoint is reachable.

    Args:
        cfg: Application configuration dict (must contain
            ``ctrader_mcp.url``).

    Returns:
        Dict with ``ctrader`` and ``mcp`` sub-dicts and an overall
        ``ok`` boolean.
    """
    ctrader = check_ctrader_running()
    mcp_url = cfg.get("ctrader_mcp", {}).get("url", "")
    mcp = check_mcp_available(mcp_url) if mcp_url else {"reachable": False, "url": "", "error": "no MCP URL configured"}

    ok = ctrader.get("running", False) and mcp.get("reachable", False)
    return {"ok": ok, "ctrader": ctrader, "mcp": mcp}