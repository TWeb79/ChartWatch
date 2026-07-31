"""SQLite storage: one row per capture cycle, recording the screenshot,
the model's raw response, the guardrail outcome, and what was ultimately
done (executed/denied/timed-out/rejected)."""

from __future__ import annotations
import sqlite3
import json
import time
import threading
from pathlib import Path
from typing import Any, Optional

from .logger import get_logger, log_event

log = get_logger("chartwatch.storage")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    screenshot_path TEXT,
    model_response TEXT,       -- raw JSON string from Ollama
    guardrail_status TEXT,     -- 'ok' | 'rejected'
    guardrail_reason TEXT,
    action_status TEXT,        -- 'executed_manual' | 'executed_auto' |
                                 -- 'denied' | 'auto_denied_timeout' |
                                 -- 'guardrail_rejected' | 'error'
    mcp_result TEXT
);
"""


class Storage:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute(_SCHEMA)
        self.conn.commit()
        self._lock = threading.Lock()

    def _execute(self, sql: str, params: tuple = ()):
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def new_cycle(self, screenshot_path: str) -> int:
        log_event(log, "storage_new_cycle", {"screenshot_path": screenshot_path})
        cur = self._execute(
            "INSERT INTO cycles (ts, screenshot_path) VALUES (?, ?)",
            (time.time(), screenshot_path),
        )
        cycle_id = cur.lastrowid
        log_event(log, "storage_new_cycle_ok", {"cycle_id": cycle_id})
        return cycle_id

    def set_model_response(self, cycle_id: int, response: dict[str, Any]) -> None:
        log_event(log, "storage_set_model_response", {"cycle_id": cycle_id})
        self._execute(
            "UPDATE cycles SET model_response = ? WHERE id = ?",
            (json.dumps(response), cycle_id),
        )

    def set_guardrail(self, cycle_id: int, status: str, reason: Optional[str]) -> None:
        log_event(log, "storage_set_guardrail", {"cycle_id": cycle_id, "status": status})
        self._execute(
            "UPDATE cycles SET guardrail_status = ?, guardrail_reason = ? WHERE id = ?",
            (status, reason, cycle_id),
        )

    def set_action(self, cycle_id: int, status: str, mcp_result: Optional[dict] = None) -> None:
        log_event(log, "storage_set_action", {"cycle_id": cycle_id, "status": status})
        self._execute(
            "UPDATE cycles SET action_status = ?, mcp_result = ? WHERE id = ?",
            (status, json.dumps(mcp_result) if mcp_result else None, cycle_id),
        )

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        cur = self._execute(
            "SELECT * FROM cycles ORDER BY ts DESC LIMIT ?", (limit,)
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def daily_pnl_pct(self, account_value: float = 0.0) -> float:
        """Compute today's realized PnL as a percentage of account value.
        Returns 0.0 if no closed trades exist or if account_value is zero."""
        today_start = time.mktime(time.localtime()) // 86400 * 86400
        rows = self._execute(
            "SELECT action_status, mcp_result FROM cycles WHERE ts >= ?",
            (today_start,),
        ).fetchall()
        total_pnl = 0.0
        for status, result_json in rows:
            if status not in ("executed_auto", "executed_manual"):
                continue
            if not result_json:
                continue
            try:
                result = json.loads(result_json)
            except (json.JSONDecodeError, TypeError):
                continue
            pnl = result.get("pnl")
            if pnl is not None:
                total_pnl += float(pnl)
        if account_value <= 0:
            return 0.0
        return (total_pnl / account_value) * 100
