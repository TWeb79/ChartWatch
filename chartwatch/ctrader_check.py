"""Prerequisite checks for cTrader and the MCP server.

Provides functions to verify that the cTrader application is running
and that the MCP endpoint is reachable before attempting a capture
or analysis cycle.

Author: Inventions4All - github:TWeb79
Version: 1.1.0  (deployment: 2026-08-02)
"""

from __future__ import annotations
import subprocess
import urllib.request
from typing import Any


def check_ctrader_running() -> dict[str, Any]:
    """Check whether the cTrader application process is running on macOS.

    Uses ``pgrep`` to look for a process matching ``cTrader``. On macOS
    the actual process name is ``cTrader.Mac`` (the executable inside the
    .app bundle), so a partial match via ``-f`` is used instead of exact
    match (``-x``).

    Returns:
        Dict with ``running`` (bool) and ``process_name`` (str).
    """
    try:
        result = subprocess.run(
            ["pgrep", "-f", "cTrader"],
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

    The MCP server uses Streamable HTTP transport — a plain GET to the
    MCP URL returns HTTP 400 (Bad Request) because it expects MCP
    protocol messages, not a plain HTTP GET. Therefore, any HTTP
    response (including 4xx) means the server is running and reachable.
    Only connection refused or timeout counts as unreachable.

    Args:
        url: The MCP server URL (e.g. ``http://127.0.0.1:9876/mcp/``).
        timeout: Maximum seconds to wait for a response.

    Returns:
        Dict with ``reachable`` (bool), ``url`` (str), and optional
        ``status`` or ``error`` fields.
    """
    import urllib.error
    result: dict[str, Any] = {"url": url, "reachable": False}
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result["reachable"] = True
            result["status"] = resp.status
    except urllib.error.HTTPError as e:
        # HTTP 400 from the MCP server is expected for a plain GET —
        # the server is running and responding.
        result["reachable"] = True
        result["status"] = e.code
    except Exception as e:
        result["error"] = str(e)
    return result


def check_prerequisites(cfg: dict[str, Any]) -> dict[str, Any]:
    """Run all prerequisite checks and return a combined status.

    Checks:
    1. MCP server endpoint is reachable.
    2. If MCP is reachable, cTrader is implied to be running (the MCP
       server is provided by cTrader), so the process check is skipped.
    3. If MCP is NOT reachable, check if the cTrader process is running
       to help the user diagnose the issue.

    Args:
        cfg: Application configuration dict (must contain
            ``ctrader_mcp.url``).

    Returns:
        Dict with ``ctrader`` and ``mcp`` sub-dicts and an overall
        ``ok`` boolean.  ``ok`` is ``True`` when MCP is reachable (cTrader
        is implied).
    """
    mcp_url = cfg.get("ctrader_mcp", {}).get("url", "")
    mcp = check_mcp_available(mcp_url) if mcp_url else {"reachable": False, "url": "", "error": "no MCP URL configured"}

    # Only check the cTrader process when MCP is unreachable, since the
    # MCP server is provided by cTrader — if MCP is up, cTrader is running.
    if mcp.get("reachable", False):
        ctrader = {"running": True, "process_name": "cTrader", "implied": True}
    else:
        ctrader = check_ctrader_running()

    ok = mcp.get("reachable", False)
    return {"ok": ok, "ctrader": ctrader, "mcp": mcp}