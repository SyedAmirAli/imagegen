"""Persistent, crash-safe run state.

The state file is the single source of truth for what has been generated. It is
written atomically after every item, so killing the process at any moment leaves
a valid file behind and the next run picks up exactly where this one stopped.

Disk always wins over bookkeeping: `reconcile()` promotes any item whose output
file already exists to `done`, which is what makes a hard crash (or a manually
dropped-in image) recoverable without regenerating anything.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .logging_utils import now_iso

SCHEMA_VERSION = 2
STATUSES = ("pending", "done", "failed", "skipped")


class Progress:
    def __init__(self, path: Path, project: str, backend: str):
        self.path = path
        self.data: dict = {
            "schema_version": SCHEMA_VERSION,
            "project": project,
            "backend": backend,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "total": 0,
            "counts": {s: 0 for s in STATUSES},
            "last_completed_id": None,
            "items": {},
        }
        if path.is_file():
            self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        try:
            loaded = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            backup = self.path.with_suffix(".corrupt.json")
            self.path.replace(backup)
            raise RuntimeError(
                f"state file was unreadable ({exc}); moved to {backup.name}. "
                "Rerun to rebuild it from the prompt folder and the files on disk."
            ) from exc
        if loaded.get("schema_version") != SCHEMA_VERSION:
            raise RuntimeError(
                f"state file {self.path} has schema {loaded.get('schema_version')}, "
                f"this build writes {SCHEMA_VERSION}. Move it aside to rebuild."
            )
        self.data.update(loaded)
        self.data.setdefault("items", {})

    def save(self) -> None:
        counts = {s: 0 for s in STATUSES}
        for item in self.data["items"].values():
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        self.data["counts"] = counts
        self.data["total"] = len(self.data["items"])
        self.data["updated_at"] = now_iso()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=False))
        os.replace(tmp, self.path)   # atomic on POSIX

    # -- item bookkeeping --------------------------------------------------

    def sync(self, jobs) -> dict[str, int]:
        """Add newly-seen jobs, retire prompts that disappeared, flag edits."""
        items = self.data["items"]
        stats = {"added": 0, "orphaned": 0, "changed": 0}
        live_ids = set()

        for job in jobs:
            live_ids.add(job.id)
            item = items.get(job.id)
            if item is None:
                items[job.id] = {
                    "status": "pending",
                    "prompt_file": job.rel_source,
                    "output_file": job.rel_output,
                    "prompt_sha": job.prompt_sha,
                    "attempts": 0,
                    "started_at": None,
                    "finished_at": None,
                    "error": None,
                    "provider_image_id": None,
                    "notes": [],
                }
                stats["added"] += 1
                continue
            item["prompt_file"] = job.rel_source
            item["output_file"] = job.rel_output
            if item.get("prompt_sha") != job.prompt_sha:
                item["prompt_changed"] = True
                stats["changed"] += 1

        # An item whose prompt file vanished stays in the state file (its image
        # is still on disk) but is flagged so it never gets queued again.
        for item_id, item in items.items():
            if item_id not in live_ids:
                if not item.get("orphaned"):
                    stats["orphaned"] += 1
                item["orphaned"] = True
            else:
                item.pop("orphaned", None)
        return stats

    def reconcile(self, jobs) -> tuple[int, int]:
        """Make the state agree with what is actually on disk.

        Both directions matter. Adopting files the state does not know about is
        what makes a hard crash recoverable. Re-queueing a `done` item whose
        image has been deleted is what makes "delete it and run again" work —
        the obvious way to redo one image you were not happy with.

        Returns (adopted, requeued).
        """
        adopted = requeued = 0
        for job in jobs:
            item = self.data["items"].get(job.id)
            if item is None:
                continue
            on_disk = job.output.is_file() and job.output.stat().st_size > 0
            if on_disk and item["status"] != "done":
                item["status"] = "done"
                item["finished_at"] = item.get("finished_at") or now_iso()
                item["error"] = None
                item.setdefault("notes", []).append("adopted existing file on disk")
                adopted += 1
            elif not on_disk and item["status"] == "done":
                item["status"] = "pending"
                item["attempts"] = 0
                item["error"] = None
                item["notes"] = ["output file was removed, queued to regenerate"]
                requeued += 1
        return adopted, requeued

    def requeue(self, statuses: tuple[str, ...]) -> int:
        n = 0
        for item in self.data["items"].values():
            if item["status"] in statuses:
                item["status"] = "pending"
                item["attempts"] = 0
                item["error"] = None
                n += 1
        return n

    def requeue_changed(self) -> int:
        n = 0
        for item in self.data["items"].values():
            if item.get("prompt_changed") and item["status"] == "done":
                item["status"] = "pending"
                item["attempts"] = 0
                n += 1
        return n

    def get(self, job_id: str) -> dict:
        return self.data["items"][job_id]

    def mark_done(self, job_id: str, *, provider_image_id: str | None, notes: list[str]) -> None:
        item = self.get(job_id)
        item.update(
            status="done",
            finished_at=now_iso(),
            error=None,
            provider_image_id=provider_image_id,
            notes=notes,
        )
        item.pop("prompt_changed", None)
        self.data["last_completed_id"] = job_id

    def mark_failed(self, job_id: str, error: str) -> None:
        item = self.get(job_id)
        item.update(status="failed", error=error[:4000], finished_at=now_iso())

    def mark_skipped(self, job_id: str, reason: str) -> None:
        item = self.get(job_id)
        item.update(status="skipped", error=reason[:4000])

    @property
    def counts(self) -> dict:
        return self.data["counts"]
