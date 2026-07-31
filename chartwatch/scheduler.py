"""Orchestrates one full cycle: capture -> analyze -> validate -> guardrail
-> approve (auto or via UI, with 60s timeout) -> execute -> log. Runs on an
asyncio loop and pushes state changes out over a callback so api.py can
forward them to connected browsers via WebSocket."""

from __future__ import annotations
import asyncio
import time
from typing import Any, Callable, Optional

from . import capture, decision, guardrails, ollama_client, storage
from .logger import get_logger, log_event
from .mcp_client import CTraderMCPClient

log = get_logger("chartwatch.scheduler")


class PendingApproval:
    def __init__(self, cycle_id: int, decision_data: dict[str, Any], timeout_s: int, loop: asyncio.AbstractEventLoop):
        self.cycle_id = cycle_id
        self.decision = decision_data
        self.created_at = time.time()
        self.timeout_s = timeout_s
        self.event = asyncio.Event()
        self.result: Optional[str] = None  # "approved" | "denied" | "timeout"
        self._loop = loop

    def resolve(self, result: str) -> None:
        self.result = result
        self._loop.call_soon_threadsafe(self.event.set)


class Scheduler:
    def __init__(self, cfg: dict[str, Any], store: storage.Storage, on_event: Callable):
        self.cfg = cfg
        self.store = store
        self.on_event = on_event  # async callback(event_type: str, payload: dict)
        self.mcp = CTraderMCPClient(cfg["ctrader_mcp"]["url"])
        self.pending: Optional[PendingApproval] = None
        self._running = False
        self._loop = asyncio.get_running_loop()
        self._ollama_times: list[float] = []
        self._ollama_window = 10

    async def start(self):
        self._running = True
        interval = self.cfg["interval_minutes"]
        if interval < 1:
            raise ValueError(
                f"interval_minutes must be >= 1, got {interval}"
            )

        max_retries = 5
        delay = 1.0
        max_delay = 30.0
        for attempt in range(1, max_retries + 1):
            try:
                await self.mcp.connect()
                break
            except Exception as e:
                if attempt == max_retries:
                    raise RuntimeError(
                        f"Failed to connect to MCP server after {max_retries} attempts: {e}"
                    ) from e
                log_event(log, "mcp_connect_retry", {
                    "attempt": attempt,
                    "max_retries": max_retries,
                    "delay": delay,
                    "error": str(e),
                })
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)

        try:
            while self._running:
                if not self.mcp.session:
                    try:
                        await self.mcp.connect()
                    except Exception as e:
                        await self.on_event("error", {
                            "message": f"MCP reconnection failed: {e}"
                        })
                        await asyncio.sleep(5)
                        continue
                try:
                    await self._run_cycle()
                except Exception as e:
                    await self.on_event("error", {"message": str(e)})

                configured_interval_s = self.cfg["interval_minutes"] * 60
                min_interval_s = self.min_interval_seconds()
                actual_sleep = max(configured_interval_s, min_interval_s)
                if actual_sleep > configured_interval_s:
                    await self.on_event("log", {
                        "message": (
                            f"Ollama avg response: {self.avg_ollama_time():.1f}s "
                            f"→ sleeping {actual_sleep / 60:.1f}min "
                            f"(min: {min_interval_s / 60:.1f}min)"
                        )
                    })
                await asyncio.sleep(actual_sleep)
        finally:
            await self.mcp.close()

    def stop(self):
        self._running = False

    async def trigger_cycle(self):
        """Run a single cycle immediately without waiting for the interval."""
        try:
            if not self.mcp.session:
                max_retries = 3
                delay = 1.0
                for attempt in range(1, max_retries + 1):
                    try:
                        await self.mcp.connect()
                        break
                    except Exception as e:
                        if attempt == max_retries:
                            raise RuntimeError(
                                f"Failed to connect to MCP server after {max_retries} attempts: {e}"
                            ) from e
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, 30.0)
            await self._run_cycle()
        except Exception as e:
            await self.on_event("error", {"message": str(e)})

    async def _run_cycle(self):
        cfg = self.cfg
        window_id = cfg.get("target_window_id")
        if not window_id:
            log_event(log, "error", {"message": "no target window configured"})
            await self.on_event("error", {"message": "no target window configured"})
            return

        log_event(log, "cycle_start", {"window_id": window_id})
        await self.on_event("cycle_start", {})

        # 1. capture
        log_event(log, "capture_start", {"window_id": window_id})
        screenshot_path = capture.capture_window(
            window_id, cfg["storage"]["screenshot_dir"]
        )
        cycle_id = self.store.new_cycle(screenshot_path)
        log_event(log, "capture_complete", {"cycle_id": cycle_id, "path": screenshot_path})
        await self.on_event("capture", {"cycle_id": cycle_id, "path": screenshot_path})
        await self.on_event("log", {"message": f"Screenshot taken and stored: {screenshot_path}"})

        # 2. current position context (best-effort; TODO wire real symbol)
        try:
            log_event(log, "mcp_call", {"tool": "get_positions", "status": "started"})
            positions = await self.mcp.get_open_positions()
            log_event(log, "mcp_response", {"tool": "get_positions", "status": "ok", "count": len(positions)})
        except Exception as e:
            log_event(log, "mcp_error", {"tool": "get_positions", "error": str(e)})
            positions = []
        position_context = positions[0] if positions else None

        # 3. ask Ollama (run in thread to avoid blocking the event loop)
        await self.on_event("log", {"message": "Submitting screenshot to Ollama for analysis..."})
        log_event(log, "ollama_submit", {"cycle_id": cycle_id, "model": cfg["ollama"]["model"]})
        try:
            ollama_start = time.monotonic()
            raw = await asyncio.to_thread(
                ollama_client.analyze,
                screenshot_path,
                position_context,
                model=cfg["ollama"]["model"],
                host=cfg["ollama"]["host"],
                instruction_file=cfg["ollama"].get("instruction_file", ""),
            )
            ollama_elapsed = time.monotonic() - ollama_start
            self._ollama_times.append(ollama_elapsed)
            if len(self._ollama_times) > self._ollama_window:
                self._ollama_times = self._ollama_times[-self._ollama_window:]
            log_event(log, "ollama_timing", {
                "cycle_id": cycle_id,
                "elapsed_s": round(ollama_elapsed, 2),
                "avg_s": round(self.avg_ollama_time(), 2),
            })
        except Exception as e:
            log_event(log, "ollama_error", {"cycle_id": cycle_id, "error": str(e)})
            self.store.set_action(cycle_id, "error")
            await self.on_event("error", {"cycle_id": cycle_id, "message": str(e)})
            return
        self.store.set_model_response(cycle_id, raw)
        log_event(log, "ollama_response", {"cycle_id": cycle_id, "response": raw})
        await self.on_event("model_response", {"cycle_id": cycle_id, "response": raw})
        await self.on_event("log", {"message": "Ollama response received", "response": raw})

        # 4. validate shape
        try:
            log_event(log, "decision_validate", {"cycle_id": cycle_id})
            d = decision.validate(raw)
            log_event(log, "decision_valid", {"cycle_id": cycle_id, "decision": d})
        except decision.InvalidDecision as e:
            log_event(log, "decision_invalid", {"cycle_id": cycle_id, "error": str(e)})
            self.store.set_action(cycle_id, "error")
            await self.on_event("error", {"cycle_id": cycle_id, "message": str(e)})
            return

        # 5. guardrails
        try:
            pip_size = cfg.get("trading", {}).get("pip_size", 0.0001)
            log_event(log, "guardrail_check", {"cycle_id": cycle_id, "pip_size": pip_size})
            guardrails.check(
                d,
                current_price=None,
                open_positions_count=len(positions),
                daily_pnl_pct=self.store.daily_pnl_pct(
                account_value=cfg.get("trading", {}).get("account_value", 0.0)
            ),
                limits=cfg["risk_limits"],
                pip_size=pip_size,
            )
            self.store.set_guardrail(cycle_id, "ok", None)
            log_event(log, "guardrail_ok", {"cycle_id": cycle_id})
        except guardrails.GuardrailRejection as e:
            log_event(log, "guardrail_rejected", {"cycle_id": cycle_id, "reason": str(e)})
            self.store.set_guardrail(cycle_id, "rejected", str(e))
            self.store.set_action(cycle_id, "guardrail_rejected")
            await self.on_event(
                "guardrail_rejected", {"cycle_id": cycle_id, "reason": str(e)}
            )
            return

        # nothing actionable proposed
        if not d.get("new_trade") and d.get("open_position_action") in (None, "hold"):
            self.store.set_action(cycle_id, "no_action")
            log_event(log, "no_action", {"cycle_id": cycle_id})
            await self.on_event("no_action", {"cycle_id": cycle_id})
            return

        # 6. approval
        if cfg["approval"]["auto_approve"]:
            log_event(log, "execute_auto", {"cycle_id": cycle_id})
            await self._execute(cycle_id, d, position_context)
            self.store.set_action(cycle_id, "executed_auto")
            await self.on_event("executed", {"cycle_id": cycle_id, "mode": "auto"})
        else:
            approval = PendingApproval(cycle_id, d, cfg["approval"]["timeout_seconds"], self._loop)
            self.pending = approval
            await self.on_event(
                "approval_requested",
                {"cycle_id": cycle_id, "decision": d, "timeout_s": approval.timeout_s},
            )
            log_event(log, "approval_pending", {"cycle_id": cycle_id, "timeout_s": approval.timeout_s})
            try:
                await asyncio.wait_for(approval.event.wait(), timeout=approval.timeout_s)
            except asyncio.TimeoutError:
                approval.result = "timeout"
                log_event(log, "approval_timeout", {"cycle_id": cycle_id})

            self.pending = None
            if approval.result == "approved":
                log_event(log, "execute_manual", {"cycle_id": cycle_id})
                await self._execute(cycle_id, d, position_context)
                self.store.set_action(cycle_id, "executed_manual")
                await self.on_event("executed", {"cycle_id": cycle_id, "mode": "manual"})
            elif approval.result == "denied":
                log_event(log, "approval_denied", {"cycle_id": cycle_id})
                self.store.set_action(cycle_id, "denied")
                await self.on_event("denied", {"cycle_id": cycle_id})
            else:
                log_event(log, "approval_auto_denied_timeout", {"cycle_id": cycle_id})
                self.store.set_action(cycle_id, "auto_denied_timeout")
                await self.on_event("auto_denied_timeout", {"cycle_id": cycle_id})

    async def _execute(
        self, cycle_id: int, d: dict[str, Any], position_context: Optional[dict]
    ) -> None:
        result = {}
        if position_context:
            action = d.get("open_position_action")
            pos_id = position_context.get("id")
            if isinstance(pos_id, str):
                if action == "close":
                    result = await self.mcp.close_position(pos_id)
                elif action == "trail_sl" and d.get("new_sl") is not None:
                    result = await self.mcp.modify_sl(pos_id, d["new_sl"])

        if d.get("new_trade"):
            t = d["new_trade"]
            default_symbol = self.cfg.get("trading", {}).get("default_symbol")
            symbol = position_context.get("symbol") if position_context else default_symbol
            if not isinstance(symbol, str):
                symbol = "UNKNOWN"
            result = await self.mcp.open_position(
                symbol=symbol,
                direction=t["direction"],
                volume=self.cfg["risk_limits"]["max_position_size"],
                sl=t["sl"],
                tp=t["tp"],
            )

        self.store.set_action(cycle_id, "executed", mcp_result=result)

    def avg_ollama_time(self) -> float:
        if not self._ollama_times:
            return 0.0
        return sum(self._ollama_times) / len(self._ollama_times)

    def min_interval_seconds(self) -> float:
        return max(self.avg_ollama_time() + 30.0, 300.0)

    def resolve_pending(self, cycle_id: int, decision_str: str) -> bool:
        if self.pending and self.pending.cycle_id == cycle_id:
            self.pending.resolve(decision_str)
            return True
        return False
