"""Orchestrates one full cycle: capture -> analyze -> validate -> guardrail
-> approve (auto or via UI, with 60s timeout) -> execute -> log. Runs on an
asyncio loop and pushes state changes out over a callback so api.py can
forward them to connected browsers via WebSocket."""

from __future__ import annotations
import asyncio
import time
from typing import Any, Callable, Optional

from . import capture, ollama_client, decision, guardrails, storage
from .mcp_client import CTraderMCPClient


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

    async def start(self):
        self._running = True
        while self._running:
            try:
                await self._run_cycle()
            except Exception as e:
                await self.on_event("error", {"message": str(e)})
            await asyncio.sleep(self.cfg["interval_minutes"] * 60)

    def stop(self):
        self._running = False

    async def trigger_cycle(self):
        """Run a single cycle immediately without waiting for the interval."""
        try:
            await self._run_cycle()
        except Exception as e:
            await self.on_event("error", {"message": str(e)})

    async def _run_cycle(self):
        cfg = self.cfg
        window_id = cfg.get("target_window_id")
        if not window_id:
            await self.on_event("error", {"message": "no target window configured"})
            return

        await self.on_event("cycle_start", {})

        # 1. capture
        screenshot_path = capture.capture_window(
            window_id, cfg["storage"]["screenshot_dir"]
        )
        cycle_id = self.store.new_cycle(screenshot_path)
        await self.on_event("capture", {"cycle_id": cycle_id, "path": screenshot_path})
        await self.on_event("log", {"message": f"Screenshot taken and stored: {screenshot_path}"})

        # 2. current position context (best-effort; TODO wire real symbol)
        try:
            positions = await self.mcp.get_open_positions()
        except Exception:
            positions = []
        position_context = positions[0] if positions else None

        # 3. ask Ollama (run in thread to avoid blocking the event loop)
        await self.on_event("log", {"message": "Submitting screenshot to Ollama for analysis..."})
        raw = await asyncio.to_thread(
            ollama_client.analyze,
            screenshot_path,
            position_context,
            model=cfg["ollama"]["model"],
            host=cfg["ollama"]["host"],
        )
        self.store.set_model_response(cycle_id, raw)
        await self.on_event("model_response", {"cycle_id": cycle_id, "response": raw})
        await self.on_event("log", {"message": "Ollama response received", "response": raw})

        # 4. validate shape
        try:
            d = decision.validate(raw)
        except decision.InvalidDecision as e:
            self.store.set_action(cycle_id, "error")
            await self.on_event("error", {"cycle_id": cycle_id, "message": str(e)})
            return

        # 5. guardrails
        try:
            pip_size = cfg.get("trading", {}).get("pip_size", 0.0001)
            guardrails.check(
                d,
                current_price=None,  # TODO: pull from position_context / MCP quote tool
                open_positions_count=len(positions),
                daily_pnl_pct=self.store.daily_pnl_pct(),
                limits=cfg["risk_limits"],
                pip_size=pip_size,
            )
            self.store.set_guardrail(cycle_id, "ok", None)
        except guardrails.GuardrailRejection as e:
            self.store.set_guardrail(cycle_id, "rejected", str(e))
            self.store.set_action(cycle_id, "guardrail_rejected")
            await self.on_event(
                "guardrail_rejected", {"cycle_id": cycle_id, "reason": str(e)}
            )
            return

        # nothing actionable proposed
        if not d.get("new_trade") and d.get("open_position_action") in (None, "hold"):
            self.store.set_action(cycle_id, "no_action")
            await self.on_event("no_action", {"cycle_id": cycle_id})
            return

        # 6. approval
        if cfg["approval"]["auto_approve"]:
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
            try:
                await asyncio.wait_for(approval.event.wait(), timeout=approval.timeout_s)
            except asyncio.TimeoutError:
                approval.result = "timeout"

            self.pending = None
            if approval.result == "approved":
                await self._execute(cycle_id, d, position_context)
                self.store.set_action(cycle_id, "executed_manual")
                await self.on_event("executed", {"cycle_id": cycle_id, "mode": "manual"})
            elif approval.result == "denied":
                self.store.set_action(cycle_id, "denied")
                await self.on_event("denied", {"cycle_id": cycle_id})
            else:
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

    def resolve_pending(self, cycle_id: int, decision_str: str) -> bool:
        if self.pending and self.pending.cycle_id == cycle_id:
            self.pending.resolve(decision_str)
            return True
        return False
