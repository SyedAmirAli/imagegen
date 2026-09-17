"""Formatting utilities for display strings."""
from __future__ import annotations
import re
from datetime import datetime, timezone

def duration_str(seconds: float) -> str:
    """Format seconds as a human-readable duration string."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s"

def timestamp_str(iso: str) -> str:
    """Format an ISO 8601 string as a user-friendly local time."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()
        now = datetime.now().astimezone()
        if local.date() == now.date():
            return f"Today {local.strftime('%I:%M %p')}"
        elif (now.date() - local.date()).days == 1:
            return f"Yesterday {local.strftime('%I:%M %p')}"
        else:
            return local.strftime("%b %d, %Y %I:%M %p")
    except (ValueError, TypeError):
        return iso

def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()

def quote_path(path: str) -> str:
    """Quote a Windows path for safe CLI insertion."""
    if not path:
        return ""
    # Always double-quote paths on Windows
    path = path.replace('"', '\\"')
    return f'"{path}"'

def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from terminal output."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def short_command(command: str, max_len: int = 80) -> str:
    """Truncate a command string for display."""
    if len(command) <= max_len:
        return command
    return command[:max_len - 3] + "..."
