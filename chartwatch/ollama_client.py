"""Sends the screenshot + current position context to a local Ollama vision
model and returns a parsed decision dict. Forces JSON-only output so the
rest of the pipeline never has to parse free text."""

from __future__ import annotations
import json
import base64
from typing import Any, Optional
import ollama

SYSTEM_PROMPT = """You are a trading chart analysis assistant. You will be shown \
a screenshot of a trading platform chart. Analyze price action, visible \
indicators, and candle structure. You will also be told whether a position \
is currently open and its details, if any.

Respond with ONLY valid JSON, no markdown fences, no extra text, matching \
exactly this schema:

{
  "assessment": "<2-4 sentence summary of what you see and why>",
  "trend_10min": "up" | "down" | "sideways",
  "confidence": <float 0-1>,
  "open_position_action": "hold" | "close" | "trail_sl" | null,
  "new_sl": <number or null>,
  "new_trade": {
    "direction": "buy" | "sell",
    "sl": <number>,
    "tp": <number>
  } | null
}

Rules:
- If no position is open and you do not see a clear setup, set new_trade to null.
- open_position_action is null if there is no open position.
- Never propose new_trade AND open_position_action=close in the same response \
  unless you mean to close-then-reopen — prefer being conservative.
- If you are not confident, prefer "hold" / null over speculative action.
"""


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def analyze(
    screenshot_path: str,
    position_context: Optional[dict[str, Any]],
    model: str,
    host: str,
) -> dict[str, Any]:
    client = ollama.Client(host=host)

    context_str = (
        json.dumps(position_context) if position_context else "No open position."
    )

    response = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Current position context: {context_str}",
                "images": [_encode_image(screenshot_path)],
            },
        ],
        format="json",  # Ollama's structured-output mode where supported
        options={"temperature": 0.2},
    )

    raw = response["message"]["content"]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON: {raw!r}") from e
