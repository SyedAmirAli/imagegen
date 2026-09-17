from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import uuid

@dataclass
class HistoryEntry:
    id: str
    command: str                    # full CLI command string
    command_name: str               # e.g. "run"
    inputs: dict[str, Any]          # raw form values
    status: str                     # "running", "success", "failed", "cancelled"
    started_at: str                 # ISO 8601
    finished_at: str = ""
    duration_seconds: float = 0.0
    exit_code: int | None = None
    output: str = ""                # captured terminal output

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> HistoryEntry:
        return cls(**data)
