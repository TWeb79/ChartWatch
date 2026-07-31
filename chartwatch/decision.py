"""Validates the raw dict from Ollama before anything downstream trusts it.
Deliberately strict: malformed or nonsensical output is rejected rather than
guessed at."""

from __future__ import annotations
from typing import Any


class InvalidDecision(Exception):
    pass


VALID_TRENDS = {"up", "down", "sideways"}
VALID_POSITION_ACTIONS = {"hold", "close", "trail_sl", None}
VALID_DIRECTIONS = {"buy", "sell"}


def validate(d: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(d, dict):
        raise InvalidDecision("response is not a JSON object")

    for key in ("assessment", "trend_10min", "confidence"):
        if key not in d:
            raise InvalidDecision(f"missing required field: {key}")

    if d["trend_10min"] not in VALID_TRENDS:
        raise InvalidDecision(f"invalid trend_10min: {d['trend_10min']}")

    conf = d["confidence"]
    if not isinstance(conf, (int, float)) or not (0 <= conf <= 1):
        raise InvalidDecision(f"confidence out of range: {conf}")

    pos_action = d.get("open_position_action")
    if pos_action not in VALID_POSITION_ACTIONS:
        raise InvalidDecision(f"invalid open_position_action: {pos_action}")

    new_trade = d.get("new_trade")
    if new_trade is not None:
        if not isinstance(new_trade, dict):
            raise InvalidDecision("new_trade must be an object or null")
        for key in ("direction", "sl", "tp"):
            if key not in new_trade:
                raise InvalidDecision(f"new_trade missing field: {key}")
        if new_trade["direction"] not in VALID_DIRECTIONS:
            raise InvalidDecision(f"invalid direction: {new_trade['direction']}")
        if not isinstance(new_trade["sl"], (int, float)) or not isinstance(
            new_trade["tp"], (int, float)
        ):
            raise InvalidDecision("sl/tp must be numeric")

    return d
