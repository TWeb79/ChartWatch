"""Unified LLM client that dispatches to either Ollama or NVIDIA
based on the configured provider in config.yaml.

Author: Inventions4All - github:TWeb79
Version: 1.0.0  (deployment: 2026-08-01)
"""

from __future__ import annotations
from typing import Any, Optional

from .logger import get_logger, log_event

log = get_logger("chartwatch.llm")


def analyze(
    screenshot_path: str,
    position_context: Optional[dict[str, Any]],
    cfg: dict[str, Any],
    account_balance: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Analyze a screenshot using the configured LLM provider.

    Dispatches to either Ollama or NVIDIA based on ``cfg["provider"]``.

    Args:
        screenshot_path: Path to the screenshot image file.
        position_context: Current open position details, or None.
        cfg: Application configuration dict.
        account_balance: Optional dict with ``balance`` and ``currency``
            for the configured cTrader account. Included in the LLM prompt
            so the model can suggest appropriate position sizing.

    Returns:
        Parsed decision dict from the model.

    Raises:
        ValueError: If the provider is unknown or the model returns invalid data.
    """
    provider = cfg.get("provider", "ollama")
    ollama_cfg = cfg.get("ollama", {}) if provider == "ollama" else {}
    nvidia_cfg = cfg.get("nvidia", {}) if provider == "nvidia" else {}
    # Resolve model per-provider: llm_model override takes priority, then
    # the provider-specific config key.
    model = cfg.get("llm_model", "")
    if not model:
        if provider == "ollama":
            model = ollama_cfg.get("model", "")
        elif provider == "nvidia":
            model = nvidia_cfg.get("model", "")
    instruction_file = cfg.get("instruction_file", "")
    timeout = None
    if provider == "ollama":
        timeout = ollama_cfg.get("timeout", 120.0)
    elif provider == "nvidia":
        timeout = nvidia_cfg.get("timeout", 30.0)

    if provider == "ollama":
        from . import ollama_client
        log_event(log, "llm_dispatch", {"provider": "ollama", "model": model})
        return ollama_client.analyze(
            screenshot_path=screenshot_path,
            position_context=position_context,
            model=model,
            host=ollama_cfg.get("host", "http://localhost:11434"),
            instruction_file=ollama_cfg.get("instruction_file", instruction_file),
            account_balance=account_balance,
            timeout=timeout,
            system_prompt=ollama_cfg.get("prompt", ""),
        )

    if provider == "nvidia":
        from . import nvidia_client
        log_event(log, "llm_dispatch", {"provider": "nvidia", "model": model})
        return nvidia_client.analyze(
            screenshot_path=screenshot_path,
            position_context=position_context,
            model=model,
            api_key=nvidia_cfg.get("api_key", ""),
            base_url=nvidia_cfg.get("base_url", "https://integrate.api.nvidia.com/v1"),
            temperature=nvidia_cfg.get("temperature", 1),
            top_p=nvidia_cfg.get("top_p", 0.95),
            max_tokens=nvidia_cfg.get("max_tokens", 8192),
            instruction_file=nvidia_cfg.get("instruction_file", instruction_file),
            account_balance=account_balance,
            timeout=timeout,
            system_prompt=nvidia_cfg.get("prompt", ""),
        )

    raise ValueError(
        f"Unknown LLM provider: {provider!r}. "
        "Supported providers: 'ollama', 'nvidia'."
    )