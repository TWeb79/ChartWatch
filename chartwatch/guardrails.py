"""Hard limits enforced regardless of what the model says, and regardless
of auto_approve. These are the last line of defense before anything reaches
the MCP client.

Author: Inventions4All - github:TWeb79
Version: 1.0.0  (deployment: 2026-08-01)
"""

from __future__ import annotations
from typing import Any, Optional

from .logger import get_logger, log_event

log = get_logger("chartwatch.guardrails")


class GuardrailRejection(Exception):
    pass


def check(
    decision: dict[str, Any],
    current_price: Optional[float],
    open_positions_count: int,
    daily_pnl_pct: float,
    limits: dict[str, Any],
    pip_size: float = 0.0001,
) -> None:
    """Raises GuardrailRejection with a human-readable reason, or returns None."""

    if daily_pnl_pct <= -abs(limits["max_daily_loss_pct"]):
        log_event(log, "guardrail_reject", {
            "reason": f"daily loss limit hit ({daily_pnl_pct:.2f}%)",
        })
        raise GuardrailRejection(
            f"daily loss limit hit ({daily_pnl_pct:.2f}%) — no new actions today"
        )

    new_trade = decision.get("new_trade")
    if new_trade:
        if open_positions_count >= limits["max_concurrent_positions"]:
            log_event(log, "guardrail_reject", {
                "reason": f"max concurrent positions reached ({open_positions_count})",
            })
            raise GuardrailRejection(
                f"max concurrent positions reached ({open_positions_count})"
            )

        if current_price is not None:
            sl_distance = abs(current_price - new_trade["sl"])
            sl_distance_pips = sl_distance / pip_size
            if sl_distance_pips < limits["min_sl_distance_pips"]:
                log_event(log, "guardrail_reject", {
                    "reason": f"SL too close: {sl_distance_pips:.1f} pips",
                })
                raise GuardrailRejection(
                    f"SL too close: {sl_distance_pips:.1f} pips "
                    f"(min {limits['min_sl_distance_pips']})"
                )
        else:
            log_event(log, "guardrail_skip_sl_distance", {
                "reason": "current_price is None — no MCP quote tool wired; "
                          "SL distance check skipped",
            })
            log.warning(
                "SL distance guardrail skipped: current_price is None. "
                "Wire an MCP quote tool to enable this check."
            )

        direction = new_trade["direction"]
        sl, tp = new_trade["sl"], new_trade["tp"]
        if direction == "buy" and not (sl < tp):
            log_event(log, "guardrail_reject", {"reason": "buy order: SL must be below TP"})
            raise GuardrailRejection("buy order: SL must be below TP")
        if direction == "sell" and not (sl > tp):
            log_event(log, "guardrail_reject", {"reason": "sell order: SL must be above TP"})
            raise GuardrailRejection("sell order: SL must be above TP")

    # max_position_size is enforced in scheduler.py:_execute() where volume is set —
    # see scheduler.py:_execute().
