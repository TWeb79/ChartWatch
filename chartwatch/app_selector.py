"""Enumerates on-screen windows via Quartz so the web UI can offer a picker.
Requires Screen Recording permission for the terminal/Python process
(System Settings -> Privacy & Security -> Screen Recording) — without it,
window titles come back empty."""

from __future__ import annotations
from typing import Optional
import Quartz

_SYSTEM_WINDOW_OWNERS = frozenset({
    "Window Server",
    "Dock",
    "SystemUIServer",
    "loginwindow",
    "Control Center",
    "Notification Center",
    "Kontrollzentrum",
    "Mitteilungszentrale",
})


def list_windows() -> list[dict]:
    """Returns visible, named windows: [{id, owner, title}, ...]"""
    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)

    windows = []
    for w in window_list:
        title = w.get("kCGWindowName", "") or ""
        owner = w.get("kCGWindowOwnerName", "") or ""
        wid = w.get("kCGWindowNumber")
        if owner and owner not in _SYSTEM_WINDOW_OWNERS:
            windows.append({"id": wid, "owner": owner, "title": title})
    return windows


def get_window_bounds(window_id: int) -> Optional[dict]:
    options = Quartz.kCGWindowListOptionIncludingWindow
    info = Quartz.CGWindowListCopyWindowInfo(options, window_id)
    if not info:
        return None
    bounds = info[0].get("kCGWindowBounds")
    return bounds  # {'X':.., 'Y':.., 'Width':.., 'Height':..}
