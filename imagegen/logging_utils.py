"""Console + file logging. One log file per output directory."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from . import ui

_LOG_FILE: Path | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def attach_file(path: Path) -> None:
    global _LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    _LOG_FILE = path


def log(msg: str, *, err: bool = False) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    ui.clear_live()   # never leave a transient status line half-overwritten
    print(f"{ui.paint(stamp, ui.C.GREY)} {msg}",
          file=sys.stderr if err else sys.stdout, flush=True)
    if _LOG_FILE is not None:
        try:
            with _LOG_FILE.open("a") as fh:
                # the file stays plain text: a log full of escape codes cannot be grepped
                fh.write(f"[{stamp}] {ui.strip(msg)}\n")
        except OSError:
            pass


def rule(char: str = "─", width: int = 72, style: str = "") -> None:
    line = char * width
    log(ui.paint(line, style) if style else ui.paint(line, ui.C.GREY))
