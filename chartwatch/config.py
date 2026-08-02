"""Loads and persists config.yaml. Kept as a thin wrapper around a dict so the
web UI can read/write individual fields (e.g. toggling auto_approve) without
needing a full schema migration each time.

All configured parameters in config.yaml are treated as defaults. Runtime
calculations or settings can override them via the overlay mechanism.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

from .logger import get_logger, log_event

log = get_logger("chartwatch.config")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

_lock = threading.RLock()
_overlay: dict[str, Any] = {}


def load() -> dict[str, Any]:
    log_event(log, "config_load", {"path": str(CONFIG_PATH)})
    with _lock, open(CONFIG_PATH, "r") as f:
        cfg = yaml.safe_load(f)
    log_event(log, "config_load_ok", {"keys": list(cfg.keys()) if cfg else []})
    return _apply_overlay(cfg)


def save(cfg: dict[str, Any]) -> None:
    log_event(log, "config_save", {"path": str(CONFIG_PATH)})
    with _lock, open(CONFIG_PATH, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    log_event(log, "config_save_ok", {"path": str(CONFIG_PATH)})


def update(patch: dict[str, Any]) -> dict[str, Any]:
    """Update config with a patch dict, thread-safe for the full operation.

    Loads the raw config from disk (without overlay), applies the patch,
    and saves back to disk. The overlay is not persisted.
    """
    log_event(log, "config_update", {"patch": patch})
    with _lock:
        with open(CONFIG_PATH, "r") as f:
            cfg = yaml.safe_load(f)
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
        with open(CONFIG_PATH, "w") as f:
            yaml.safe_dump(cfg, f, sort_keys=False)
    log_event(log, "config_update_ok", {"updated_keys": list(patch.keys())})
    return cfg


def set_overlay(overlay: dict[str, Any]) -> None:
    """Set runtime overlay values that override config.yaml defaults.

    This is used for calculated values or settings that should take
    precedence over config.yaml without persisting them to disk.
    """
    global _overlay
    with _lock:
        _overlay = overlay
    log_event(log, "config_overlay_set", {"keys": list(overlay.keys())})


def get_overlay() -> dict[str, Any]:
    """Get the current runtime overlay values."""
    with _lock:
        return dict(_overlay)


def _apply_overlay(cfg: dict[str, Any]) -> dict[str, Any]:
    """Merge config.yaml defaults with runtime overlay values."""
    if not _overlay:
        return cfg
    merged = dict(cfg)
    for key, value in _overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = dict(merged[key])
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def reset_overlay() -> None:
    """Clear all runtime overlay values."""
    global _overlay
    with _lock:
        _overlay = {}
    log_event(log, "config_overlay_reset", {})
