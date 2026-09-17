"""Application path utilities."""
from __future__ import annotations
import os
import sys
from pathlib import Path

APP_NAME = "ImageGen-GUI"

def app_data_dir() -> Path:
    """Return the application data directory, creating it if necessary."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d

def history_file() -> Path:
    return app_data_dir() / "history.json"

def project_root() -> Path:
    """Return the imagegen project root (parent of the gui/ package)."""
    return Path(__file__).resolve().parent.parent.parent

def venv_python() -> Path | None:
    """Return .venv Python executable if it exists."""
    root = project_root()
    candidates = [
        root / ".venv" / "Scripts" / "python.exe",  # Windows
        root / ".venv" / "bin" / "python",           # Unix
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None

def resolve_python() -> str:
    """Return the best Python executable to use for running imagegen."""
    venv = venv_python()
    if venv:
        return str(venv)
    return sys.executable
