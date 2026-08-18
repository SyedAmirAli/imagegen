"""Console + file logging. One log file per output directory."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_LOG_FILE: Path | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def attach_file(path: Path) -> None:
    global _LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    _LOG_FILE = path


def log(msg: str, *, err: bool = False) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, file=sys.stderr if err else sys.stdout, flush=True)
    if _LOG_FILE is not None:
        try:
            with _LOG_FILE.open("a") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def rule(char: str = "-", width: int = 72) -> None:
    log(char * width)
