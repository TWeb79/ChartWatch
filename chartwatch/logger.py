"""Structured debug logger that writes every interaction to debug.log.

All modules in the app use this logger via get_logger() to ensure
consistent formatting and a single log file for the entire application.

Log format: ISO-8601 timestamp | module | level | event_type | details (JSON)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_FILE = str(Path(__file__).resolve().parent.parent / "debug.log")

_root_logger: logging.Logger | None = None


def get_logger(name: str) -> logging.Logger:
    """Return or create a named logger that writes structured JSON to debug.log."""
    global _root_logger
    if _root_logger is None:
        _root_logger = _setup_root_logger()

    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger


def _setup_root_logger() -> logging.Logger:
    """Set up the root logger with a file handler writing JSON lines to debug.log."""
    root = logging.getLogger("chartwatch")
    root.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(file_handler)

    return root


def log_event(
    logger: logging.Logger,
    event_type: str,
    details: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    """Write a structured log event to debug.log.

    Args:
        logger: The named logger instance.
        event_type: Category of the event (e.g. "cycle_start", "mcp_call").
        details: Optional dict of additional context to include.
        level: Log level — "debug", "info", "warning", "error".
    """
    entry: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
    }
    if details:
        entry["details"] = details

    message = json.dumps(entry, default=str)
    log_method = getattr(logger, level, logger.info)
    log_method(message)