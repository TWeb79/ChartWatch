"""Sends the screenshot + current position context to an NVIDIA NIM endpoint
via the OpenAI-compatible API and returns a parsed decision dict.

Uses the OpenAI SDK with the NVIDIA base URL. The API key is read from
the config and must be set manually by the user.

Author: Inventions4All - github:TWeb79
Version: 1.0.0  (deployment: 2026-08-01)
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

from .llm_utils import strip_markdown_code_fence
from .logger import get_logger, log_event

log = get_logger("chartwatch.nvidia")

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
    position_context: dict[str, Any] | None,
    model: str,
    api_key: str,
    base_url: str,
    temperature: float,
    top_p: float,
    max_tokens: int,
    instruction_file: str = "",
    account_balance: dict[str, Any] | None = None,
    timeout: float = 30.0,
    system_prompt: str = SYSTEM_PROMPT,
) -> dict[str, Any]:
    """Analyze a screenshot using the NVIDIA NIM vision model.

    Args:
        screenshot_path: Path to the screenshot image.
        position_context: Current open position details, or None.
        model: NVIDIA model name to use.
        api_key: NVIDIA API key.
        base_url: NVIDIA NIM base URL.
        temperature: Sampling temperature.
        top_p: Top-p sampling.
        max_tokens: Maximum output tokens.
        instruction_file: Optional path to a custom instruction file.
        account_balance: Optional dict with ``balance`` and ``currency``
            for the configured cTrader account, included in the prompt
            so the model can suggest appropriate position sizing.
        timeout: Maximum seconds to wait for the API response.
        system_prompt: System prompt override; defaults to the module-level
            ``SYSTEM_PROMPT``. If the config provides a ``nvidia.prompt``
            field, that value is used instead for richer instructions.

    Returns:
        Parsed decision dict from the model.

    Raises:
        ValueError: If the model returns empty or non-JSON output.
    """
    if not system_prompt:
        system_prompt = SYSTEM_PROMPT
    log_event(log, "nvidia_analyze_start", {
        "screenshot": screenshot_path,
        "model": model,
        "base_url": base_url,
        "has_instruction_file": bool(instruction_file),
        "has_account_balance": account_balance is not None,
        "system_prompt_length": len(system_prompt),
    })
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )

    instruction_text = ""
    if instruction_file:
        instruction_path = Path(__file__).resolve().parent.parent / instruction_file
        if instruction_path.exists():
            instruction_text = instruction_path.read_text(encoding="utf-8")
            log_event(log, "nvidia_instruction_loaded", {"path": str(instruction_path), "length": len(instruction_text)})

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
    # NVIDIA NIM (OpenAI-compatible) expects images in the content array as
    # image_url blocks, not as a separate "images" key (which is the Ollama format).
    encoded_image = _encode_image(screenshot_path)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_content},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{encoded_image}"},
                        },
                    ],
                },
            ],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stream=False,
            timeout=timeout,
        )
    except Exception as e:
        error_msg = str(e)
        if "multimodal" in error_msg.lower() or "enable-multimodal" in error_msg.lower():
            raise ValueError(
                f"Model '{model}' does not support vision/multimodal input. "
                f"Enable multimodal processing on the NVIDIA NIM server "
                f"(--enable-multimodal flag) or switch to a vision-capable model."
            ) from e
        if "404" in error_msg and ("Not found" in error_msg or "not found" in error_msg.lower()):
            raise ValueError(
                f"Model '{model}' is not available for your NVIDIA account. "
                f"It may require special access, be region-restricted, or have been "
                f"renamed. Try a different vision-capable model from the dropdown "
                f"(e.g. 'meta/llama-3.2-11b-vision-instruct', "
                f"'google/gemma-3-27b-it', or 'nvidia/nemotron-vl-340b')."
            ) from e
        raise ValueError(f"NVIDIA API call failed: {error_msg}") from e
    chat_elapsed = time.monotonic() - chat_start
    log_event(log, "nvidia_chat_timing", {"model": model, "chat_elapsed_s": round(chat_elapsed, 2)})

    raw = response.choices[0].message.content
    log_event(log, "nvidia_analyze_complete", {"model": model, "raw_length": len(raw)})
    if not raw or not raw.strip():
        log_event(log, "nvidia_parse_error", {"model": model, "error": "empty response from model"})
        raise ValueError(f"Model returned empty response for {screenshot_path}")
    cleaned = strip_markdown_code_fence(raw)
    try:
        result = json.loads(cleaned)
        log_event(log, "nvidia_parse_ok", {"model": model})
        return result
    except json.JSONDecodeError as e:
        log_event(log, "nvidia_parse_error", {"model": model, "error": str(e)})
        raise ValueError(f"Model did not return valid JSON: {cleaned!r}") from e