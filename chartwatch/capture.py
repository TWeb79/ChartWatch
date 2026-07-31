"""Captures a screenshot of a single window (not the whole screen) using
macOS's built-in `screencapture` CLI with the -l (window id) flag."""

from __future__ import annotations
import subprocess
import time
from pathlib import Path


def capture_window(window_id: int, out_dir: str) -> str:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    filename = f"{int(time.time())}.png"
    out_path = str(Path(out_dir) / filename)

    # -l: window id, -o: no window shadow, -x: no camera sound
    result = subprocess.run(
        ["screencapture", "-l", str(window_id), "-o", "-x", out_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"screencapture failed: {result.stderr}")
    if not Path(out_path).exists():
        raise RuntimeError(
            "screencapture produced no file — window may be minimized/closed, "
            "or Screen Recording permission is missing."
        )
    return out_path
