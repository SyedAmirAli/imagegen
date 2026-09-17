"""Command history persistence service."""
from __future__ import annotations
import json
import threading
from typing import Callable

from ..utils.paths import history_file
from ..models.history_entry import HistoryEntry

MAX_HISTORY_ENTRIES = 500
SCHEMA_VERSION = 1


class HistoryService:
    """Manages loading, saving, and querying command history."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[HistoryEntry] = []
        self._listeners: list[Callable] = []
        self._load()

    # -- public API --------------------------------------------------------

    def get_entries(self) -> list[HistoryEntry]:
        """Return all history entries, newest first."""
        with self._lock:
            return list(reversed(self._entries))

    def add_entry(self, entry: HistoryEntry) -> None:
        """Add a new history entry and persist."""
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > MAX_HISTORY_ENTRIES:
                self._entries = self._entries[-MAX_HISTORY_ENTRIES:]
        self._save()
        self._notify()

    def update_entry(self, entry_id: str, **kwargs) -> None:
        """Update fields on an existing entry and persist."""
        with self._lock:
            for entry in self._entries:
                if entry.id == entry_id:
                    for key, value in kwargs.items():
                        setattr(entry, key, value)
                    break
        self._save()
        self._notify()

    def delete_entry(self, entry_id: str) -> None:
        """Remove a history entry by ID."""
        with self._lock:
            self._entries = [e for e in self._entries if e.id != entry_id]
        self._save()
        self._notify()

    def clear_all(self) -> None:
        """Remove all history entries."""
        with self._lock:
            self._entries = []
        self._save()
        self._notify()

    def get_entry(self, entry_id: str) -> HistoryEntry | None:
        """Find a history entry by ID."""
        with self._lock:
            for e in self._entries:
                if e.id == entry_id:
                    return e
        return None

    def on_change(self, listener: Callable) -> None:
        """Register a callback called whenever history changes."""
        self._listeners.append(listener)

    # -- private -----------------------------------------------------------

    def _load(self) -> None:
        """Load history from disk; silently handle corrupt or missing files."""
        path = history_file()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
                return
            entries = []
            for item in data.get("history", []):
                try:
                    entries.append(HistoryEntry.from_dict(item))
                except (TypeError, KeyError):
                    pass
            with self._lock:
                self._entries = entries
        except (json.JSONDecodeError, OSError):
            pass

    def _save(self) -> None:
        """Persist history to disk atomically."""
        path = history_file()
        with self._lock:
            data = {
                "version": SCHEMA_VERSION,
                "history": [e.to_dict() for e in self._entries],
            }
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    def _notify(self) -> None:
        for cb in self._listeners:
            try:
                cb()
            except Exception:
                pass
