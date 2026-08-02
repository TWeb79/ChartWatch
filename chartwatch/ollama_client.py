"""Sends the screenshot + current position context to a local Ollama vision
model and returns a parsed decision dict. Forces JSON-only output so the
rest of the pipeline never has to parse free text.

Author: Inventions4All - github:TWeb79
Version: 1.1.0  (deployment: 2026-08-02)
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, Optional

import ollama

from .logger import get_logger, log_event

log = get_logger("chartwatch.ollama")

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
    file_size = Path(path).stat().st_size
    max_bytes = 10 * 1024 * 1024  # 10 MB
    if file_size > max_bytes:
        raise ValueError(
            f"Screenshot too large for encoding: {file_size} bytes "
            f"(max {max_bytes}). Consider resizing before capture."
        )
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def analyze(
    screenshot_path: str,
    position_context: Optional[dict[str, Any]],
    model: str,
    host: str,
    instruction_file: str = "",
    account_balance: Optional[dict[str, Any]] = None,
    timeout: float = 120.0,
    system_prompt: str = SYSTEM_PROMPT,
) -> dict[str, Any]:
    """Analyze a screenshot using the Ollama vision model.

    Args:
        screenshot_path: Path to the screenshot image.
        position_context: Current open position details, or None.
        model: Ollama model name to use.
        host: Ollama server URL.
        instruction_file: Optional path to a custom instruction file.
        account_balance: Optional dict with ``balance`` and ``currency``
            for the configured cTrader account, included in the prompt
            so the model can suggest appropriate position sizing.
        timeout: Maximum seconds to wait for the Ollama response.
        system_prompt: System prompt override; defaults to the module-level
            ``SYSTEM_PROMPT``. If the config provides an ``ollama.prompt``
            field, that value is used instead for richer instructions.

    Returns:
        Parsed decision dict from the model.

    Raises:
        ValueError: If the model returns empty or non-JSON output.
    """
    if not system_prompt:
        system_prompt = SYSTEM_PROMPT
    log_event(log, "ollama_analyze_start", {
        "screenshot": screenshot_path,
        "model": model,
        "host": host,
        "has_instruction_file": bool(instruction_file),
        "has_account_balance": account_balance is not None,
        "system_prompt_length": len(system_prompt),
    })
    client = ollama.Client(host=host, timeout=timeout)

    instruction_text = ""
    if instruction_file:
        instruction_path = Path(__file__).resolve().parent.parent / instruction_file
        if instruction_path.exists():
            instruction_text = instruction_path.read_text(encoding="utf-8")
            log_event(log, "ollama_instruction_loaded", {"path": str(instruction_path), "length": len(instruction_text)})

    context_str = (
        json.dumps(position_context) if position_context else "No open position."
    )

    user_content = f"Current position context: {context_str}"
    if account_balance and account_balance.get("balance") is not None:
        user_content += (
            f"\n\nCurrent account balance: {account_balance['balance']} "
            f"{account_balance.get('currency', '')}".strip()
        )
    if instruction_text:
        user_content += f"\n\nAdditional instructions:\n{instruction_text}"

    chat_start = time.monotonic()
    response = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_content,
                "images": [_encode_image(screenshot_path)],
            },
        ],
        format="json",
        options={"temperature": 0.2},
    )
    chat_elapsed = time.monotonic() - chat_start
    log_event(log, "ollama_chat_timing", {"model": model, "chat_elapsed_s": round(chat_elapsed, 2)})

    raw = response["message"]["content"]
    log_event(log, "ollama_analyze_complete", {"model": model, "raw_length": len(raw)})
    if not raw or not raw.strip():
        log_event(log, "ollama_parse_error", {"model": model, "error": "empty response from model"})
        raise ValueError(f"Model returned empty response for {screenshot_path}")
    try:
        result = json.loads(raw)
        log_event(log, "ollama_parse_ok", {"model": model})
        return result
    except json.JSONDecodeError as e:
        log_event(log, "ollama_parse_error", {"model": model, "error": str(e)})
        raise ValueError(f"Model did not return valid JSON: {raw!r}") from e
