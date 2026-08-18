"""Terminal presentation: colour, a live status line, progress bars.

Everything degrades to the plain output this tool always produced. Colour is
emitted only to an interactive terminal, and the run log on disk never contains
escape codes — a log you cannot grep is not a log.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import time

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

_enabled = False
_live_len = 0        # width of the transient status line currently on screen
_live_at = 0.0       # when it was last redrawn
LIVE_FPS = 12        # cap redraws: past this the eye sees nothing and the tty churns


class C:
    """ANSI codes, blanked out when colour is off."""

    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    RED = "\x1b[31m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    BLUE = "\x1b[34m"
    MAGENTA = "\x1b[35m"
    CYAN = "\x1b[36m"
    GREY = "\x1b[90m"
    BG_GREEN = "\x1b[42m"


_CODES = {k: v for k, v in vars(C).items() if not k.startswith("_") and isinstance(v, str)}


def supports_colour(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("TERM", "") in ("dumb", ""):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def configure(force: bool | None = None) -> None:
    """force=True/False overrides detection; None auto-detects."""
    global _enabled
    _enabled = supports_colour() if force is None else force


def colour_enabled() -> bool:
    return _enabled


def paint(text: str, *styles: str) -> str:
    if not _enabled or not styles:
        return text
    return "".join(styles) + text + C.RESET


def strip(text: str) -> str:
    return ANSI_RE.sub("", text)


def width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except OSError:
        return default


# ---------------------------------------------------------------------------
# transient status line
# ---------------------------------------------------------------------------

def live(text: str, *, force: bool = False) -> None:
    """Draw a status line that the next output overwrites. No-op when piped."""
    global _live_len, _live_at
    if not _enabled:
        return
    now = time.time()
    if not force and now - _live_at < 1 / LIVE_FPS:
        return
    _live_at = now
    limit = max(20, width() - 1)
    visible = strip(text)
    if len(visible) > limit:
        text, visible = text[: limit - 1] + "…", visible[: limit - 1] + "…"
    pad = " " * max(0, _live_len - len(visible))
    sys.stdout.write("\r" + text + pad)
    sys.stdout.flush()
    _live_len = len(visible)


def clear_live() -> None:
    global _live_len
    if _live_len:
        sys.stdout.write("\r" + " " * _live_len + "\r")
        sys.stdout.flush()
        _live_len = 0


# ---------------------------------------------------------------------------
# pieces
# ---------------------------------------------------------------------------

def bar(fraction: float, size: int = 24, colour: str = C.CYAN) -> str:
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * size))
    return paint("█" * filled, colour) + paint("░" * (size - filled), C.GREY)


def duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def size_bytes(n: int) -> str:
    return f"{n / 1_048_576:.1f}MB" if n >= 1_048_576 else f"{n // 1024}KB"


class Clock:
    """Wall-clock timer plus a rolling ETA over recent item durations."""

    def __init__(self, window: int = 12):
        self.started = time.time()
        self.window = window
        self.samples: list[float] = []

    def record(self, seconds: float) -> None:
        self.samples.append(seconds)
        del self.samples[: -self.window]

    @property
    def elapsed(self) -> float:
        return time.time() - self.started

    def eta(self, remaining: int) -> str:
        if not self.samples or remaining <= 0:
            return "—"
        return duration(sum(self.samples) / len(self.samples) * remaining)
