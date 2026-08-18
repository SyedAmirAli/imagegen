"""Backend registry."""

from __future__ import annotations

from .base import Backend, BackendError, FatalBackendError, GenerationResult
from .ideogram import IdeogramBackend
from .mock import MockBackend

BACKENDS: dict[str, type[Backend]] = {
    IdeogramBackend.name: IdeogramBackend,
    MockBackend.name: MockBackend,   # offline testing
}

DEFAULT_BACKEND = IdeogramBackend.name


def get(name: str) -> type[Backend]:
    try:
        return BACKENDS[name]
    except KeyError:
        raise SystemExit(
            f"unknown backend {name!r}; available: {', '.join(sorted(BACKENDS))}"
        ) from None


__all__ = [
    "BACKENDS", "DEFAULT_BACKEND", "get",
    "Backend", "BackendError", "FatalBackendError", "GenerationResult",
]
