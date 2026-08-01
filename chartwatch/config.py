"""Loads and persists config.yaml. Kept as a thin wrapper around a dict so the
web UI can read/write individual fields (e.g. toggling auto_approve) without
needing a full schema migration each time."""

from __future__ import annotations
import yaml
import threading
from pathlib import Path
from typing import Any

from .logger import get_logger, log_event

log = get_logger("chartwatch.config")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

_lock = threading.Lock()


def load() -> dict[str, Any]:
    log_event(log, "config_load", {"path": str(CONFIG_PATH)})
    with _lock:
        with open(CONFIG_PATH, "r") as f:
            cfg = yaml.safe_load(f)
    log_event(log, "config_load_ok", {"keys": list(cfg.keys()) if cfg else []})
    return cfg


def save(cfg: dict[str, Any]) -> None:
    log_event(log, "config_save", {"path": str(CONFIG_PATH)})
    with _lock:
        with open(CONFIG_PATH, "w") as f:
            yaml.safe_dump(cfg, f, sort_keys=False)
    log_event(log, "config_save_ok", {"path": str(CONFIG_PATH)})


def update(patch: dict[str, Any]) -> dict[str, Any]:
    """Update config with a patch dict, thread-safe for the full operation."""
    log_event(log, "config_update", {"patch": patch})
    with _lock:
        cfg = load()
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
        save(cfg)
    log_event(log, "config_update_ok", {"updated_keys": list(patch.keys())})
    return cfg
