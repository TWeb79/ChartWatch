"""Loads and persists config.yaml. Kept as a thin wrapper around a dict so the
web UI can read/write individual fields (e.g. toggling auto_approve) without
needing a full schema migration each time."""

from __future__ import annotations
import yaml
import threading
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

_lock = threading.Lock()


def load() -> dict[str, Any]:
    with _lock:
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)


def save(cfg: dict[str, Any]) -> None:
    with _lock:
        with open(CONFIG_PATH, "w") as f:
            yaml.safe_dump(cfg, f, sort_keys=False)


def update(patch: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge a patch into the top-level config and persist it.
    e.g. update({"approval": {"auto_approve": True}}) merges one level deep."""
    cfg = load()
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    save(cfg)
    return cfg
