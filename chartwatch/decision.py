"""Validates the raw dict from Ollama before anything downstream trusts it.
Deliberately strict: malformed or nonsensical output is rejected rather than
guessed at."""

from __future__ import annotations
from typing import Any

from .logger import get_logger, log_event

log = get_logger("chartwatch.decision")


class InvalidDecision(Exception):
    pass


VALID_TRENDS = {"up", "down", "sideways"}
VALID_POSITION_ACTIONS = {"hold", "close", "trail_sl", None}
VALID_DIRECTIONS = {"buy", "sell"}


def validate(d: dict[str, Any]) -> dict[str, Any]:
    log_event(log, "decision_validate_start", {"keys": list(d.keys())})
    if not isinstance(d, dict):
        log_event(log, "decision_validate_error", {"reason": "not a JSON object"})
        raise InvalidDecision("response is not a JSON object")

    for key in ("assessment", "trend_10min", "confidence"):
        if key not in d:
            log_event(log, "decision_validate_error", {"reason": f"missing required field: {key}"})
            raise InvalidDecision(f"missing required field: {key}")

    if d["trend_10min"] not in VALID_TRENDS:
        log_event(log, "decision_validate_error", {"reason": f"invalid trend_10min: {d['trend_10min']}"})
        raise InvalidDecision(f"invalid trend_10min: {d['trend_10min']}")

    conf = d["confidence"]
    if not isinstance(conf, (int, float)) or not (0 <= conf <= 1):
        log_event(log, "decision_validate_error", {"reason": f"confidence out of range: {conf}"})
        raise InvalidDecision(f"confidence out of range: {conf}")

    pos_action = d.get("open_position_action")
    if pos_action not in VALID_POSITION_ACTIONS:
        log_event(log, "decision_validate_error", {"reason": f"invalid open_position_action: {pos_action}"})
        raise InvalidDecision(f"invalid open_position_action: {pos_action}")

    new_trade = d.get("new_trade")
    if new_trade is not None:
        if not isinstance(new_trade, dict):
            log_event(log, "decision_validate_error", {"reason": "new_trade must be an object or null"})
            raise InvalidDecision("new_trade must be an object or null")
        for key in ("direction", "sl", "tp"):
            if key not in new_trade:
                log_event(log, "decision_validate_error", {"reason": f"new_trade missing field: {key}"})
                raise InvalidDecision(f"new_trade missing field: {key}")
        if new_trade["direction"] not in VALID_DIRECTIONS:
            log_event(log, "decision_validate_error", {"reason": f"invalid direction: {new_trade['direction']}"})
            raise InvalidDecision(f"invalid direction: {new_trade['direction']}")
        if not isinstance(new_trade["sl"], (int, float)) or not isinstance(
            new_trade["tp"], (int, float)
        ):
            log_event(log, "decision_validate_error", {"reason": "sl/tp must be numeric"})
            raise InvalidDecision("sl/tp must be numeric")

    log_event(log, "decision_validate_ok", {})
    return d
