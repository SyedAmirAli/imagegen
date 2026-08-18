"""The contract every generator backend implements.

The runner knows nothing about Ideogram — it hands a Job to a Backend and gets
image bytes back. Adding another provider means adding one module here and
registering it; the queue, progress, retry and post-processing code is shared.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GenerationResult:
    data: bytes
    provider_image_id: str | None = None
    content_type: str = ""


class BackendError(RuntimeError):
    """Recoverable failure: the runner will retry, then move on."""


class FatalBackendError(RuntimeError):
    """Unrecoverable (not signed in, browser gone): the runner stops the batch."""


class Backend(abc.ABC):
    name: str = "base"

    @staticmethod
    def add_arguments(parser) -> None:
        """Register backend-specific CLI flags."""

    def __init__(self, args):
        self.args = args
        # Set by the runner. Lets a backend report what it is waiting on while a
        # single generation is in flight, instead of the terminal going quiet.
        self.progress_hook = None

    def report(self, stage: str, fraction: float | None = None) -> None:
        if self.progress_hook is not None:
            try:
                self.progress_hook(stage, fraction)
            except Exception:
                pass   # presentation must never break a run

    @abc.abstractmethod
    def open(self) -> None:
        """Get ready to generate. Raise FatalBackendError if that is impossible."""

    @abc.abstractmethod
    def generate(self, job) -> GenerationResult:
        """Produce one image. Raise BackendError to trigger a retry."""

    def recover(self) -> None:
        """Best-effort reset between failed attempts (reload the page, etc.)."""

    def snapshot(self, path: Path) -> bool:
        """Capture debugging state for a failed attempt. True if written."""
        return False

    def close(self) -> None:
        """Release resources. Must be safe to call twice."""
