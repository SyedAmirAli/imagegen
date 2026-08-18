"""The batch loop: queue -> generate -> post-process -> record, one at a time.

Strictly sequential by design. Progress is written after every single item, so
Ctrl-C, a crash or a closed browser costs at most the image in flight.
"""

from __future__ import annotations

import os
import random
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from . import postprocess
from .backends import BackendError, FatalBackendError
from . import ui
from .logging_utils import log
from .progress import Progress


class Stop(Exception):
    """Raised internally when the batch should wind down."""


@dataclass
class RunStats:
    generated: int = 0
    failed: int = 0
    skipped: int = 0
    interrupted: bool = False
    fatal: str | None = None
    elapsed: float = 0.0


class RunLock:
    """Refuse to run two batches against one output directory."""

    def __init__(self, path: Path):
        self.path = path
        self._fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            owner = self.path.read_text().strip() if self.path.is_file() else "?"
            pid = owner.split()[0] if owner else ""
            if pid.isdigit() and not _pid_alive(int(pid)):
                log(f"   clearing stale lock from pid {pid}")
                self.path.unlink(missing_ok=True)
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            else:
                raise SystemExit(
                    f"another run holds {self.path} ({owner}). Wait for it to finish, "
                    "or delete that file if you are sure nothing is running."
                )
        os.write(self._fd, f"{os.getpid()} started".encode())
        return self

    def __exit__(self, *exc):
        if self._fd is not None:
            os.close(self._fd)
        self.path.unlink(missing_ok=True)
        return False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Runner:
    def __init__(self, *, backend, progress: Progress, jobs, opts):
        self.backend = backend
        self.progress = progress
        self.jobs = {job.id: job for job in jobs}
        self.opts = opts
        self.stats = RunStats()
        self.clock = ui.Clock()
        self._done = 0
        self._total = 0
        self._stage = ""
        self._stage_fraction = None
        self._spin = 0
        self._stop = False
        backend.progress_hook = self._on_backend_progress
        signal.signal(signal.SIGINT, self._on_sigint)
        signal.signal(signal.SIGTERM, self._on_sigint)

    SPINNER = "⣾⣽⣻⢿⡿⣟⣯⣷"

    def _on_backend_progress(self, stage: str, fraction: float | None) -> None:
        self._stage, self._stage_fraction = stage, fraction
        self._render()

    def _render(self) -> None:
        """One transient line holding the whole picture: batch, item, ETA."""
        if not ui.colour_enabled() or not self._total:
            return
        self._spin = (self._spin + 1) % len(self.SPINNER)
        fraction = self._done / self._total
        parts = [
            ui.paint(self.SPINNER[self._spin], ui.C.CYAN),
            ui.paint(f"{self._done}/{self._total}", ui.C.BOLD),
            ui.bar(fraction, 18),
            f"{fraction * 100:4.1f}%",
        ]
        tally = ui.paint(f"✓{self.stats.generated}", ui.C.GREEN)
        if self.stats.failed:
            tally += " " + ui.paint(f"✗{self.stats.failed}", ui.C.RED)
        parts.append(tally)
        if self._stage:
            stage = self._stage
            if self._stage_fraction is not None:
                stage += f" {self._stage_fraction * 100:.0f}%"
            parts.append(ui.paint(stage, ui.C.MAGENTA))
        parts.append(ui.paint(
            f"{ui.duration(self.clock.elapsed)} elapsed · eta "
            f"{self.clock.eta(self._total - self._done)}", ui.C.GREY))
        ui.live(" " + ui.paint(" · ", ui.C.GREY).join(parts))

    def _on_sigint(self, signum, frame) -> None:
        if self._stop:   # second Ctrl-C: give up immediately
            raise KeyboardInterrupt
        self._stop = True
        log(ui.paint("! interrupt received — finishing the current image, then stopping cleanly", ui.C.YELLOW, ui.C.BOLD))

    # ----------------------------------------------------------------- run

    def run(self, queue: list) -> RunStats:
        total = self._total = len(queue)
        try:
            self.backend.open()
        except FatalBackendError as exc:
            self.stats.fatal = str(exc)
            log(f"!! {exc}", err=True)
            return self.stats

        try:
            for index, job in enumerate(queue, 1):
                if self._stop:
                    break
                if self.opts.limit and self.stats.generated >= self.opts.limit:
                    log(f"--limit {self.opts.limit} reached")
                    break
                if index > 1 and not self._stop:
                    self._wait(random.uniform(self.opts.min_gap, self.opts.max_gap))
                self._run_one(job, index, total)
        except Stop:
            pass
        except KeyboardInterrupt:
            self.stats.interrupted = True
            log("! hard interrupt", err=True)
        finally:
            ui.clear_live()
            self.progress.save()
            self.backend.close()

        self.stats.interrupted = self.stats.interrupted or self._stop
        self.stats.elapsed = self.clock.elapsed
        return self.stats

    def _wait(self, seconds: float) -> None:
        """Pause between generations, keeping the status line alive."""
        deadline = time.time() + seconds
        while time.time() < deadline and not self._stop:
            self._stage = f"pausing {deadline - time.time():.0f}s"
            self._stage_fraction = None
            self._render()
            time.sleep(min(0.12, max(0.0, deadline - time.time())))

    def _run_one(self, job, index: int, total: int) -> None:
        item = self.progress.get(job.id)
        item["started_at"] = item.get("started_at") or _now()
        spec = " · ".join(filter(None, [
            job.aspect or "",
            f"{job.size[0]}x{job.size[1]}" if job.size else "",
            job.background if job.background != "unspecified" else "",
        ]))
        counter = ui.paint(f"[{index}/{total}]", ui.C.GREY)
        head = f"{counter} {ui.paint(job.id, ui.C.BOLD)}  {ui.paint(spec, ui.C.GREY)}"
        tail = ui.paint(f"  → {job.rel_output}", ui.C.GREY)
        # One line per image: at 500 images a second line doubles the scrollback
        # for a path the ✓ line already implies. It only wraps to its own line
        # when the terminal is genuinely too narrow.
        if len(ui.strip(head + tail)) + 9 <= ui.width():
            log(head + tail)
        else:
            log(head)
            log(" " * (len(f"[{index}/{total}]") + 1) + tail.lstrip())
        item_started = time.time()

        for attempt in range(1, self.opts.max_attempts + 1):
            if self._stop:
                return
            item["attempts"] = item.get("attempts", 0) + 1
            try:
                result = self.backend.generate(job)
                saved = postprocess.save_png(
                    result.data,
                    job.output,
                    size=job.size,
                    # The prompt stays the source of truth: a file that
                    # explicitly asks for an opaque background is never stripped.
                    force_background_removal=(
                        self.opts.force_background_removal and not job.forbids_transparency
                    ),
                    allow_upscale=self.opts.allow_upscale,
                    max_file_bytes=self.opts.max_file_bytes,
                )
                self.progress.mark_done(
                    job.id,
                    provider_image_id=result.provider_image_id,
                    notes=saved.notes,
                )
                self.stats.generated += 1
                self._done += 1
                self.clock.record(time.time() - item_started)
                alpha = ("transparent", ui.C.CYAN) if saved.transparent else ("opaque", ui.C.YELLOW)
                log("  " + ui.paint("✓", ui.C.GREEN, ui.C.BOLD)
                    + f"  {saved.out_size[0]}x{saved.out_size[1]}"
                    + f"  {ui.paint(alpha[0], alpha[1])}"
                    + f"  {ui.paint(ui.size_bytes(saved.bytes_written), ui.C.GREY)}"
                    + f"  {ui.paint(ui.duration(time.time() - item_started), ui.C.GREY)}")
                for note in saved.notes:
                    log("  " + ui.paint(f"· {note}", ui.C.GREY))
                self._stage = ""
                self._render()
                return

            except FatalBackendError as exc:
                self.progress.mark_failed(job.id, f"fatal: {exc}")
                self.progress.save()
                self.stats.fatal = str(exc)
                log(f"!! {exc}", err=True)
                raise Stop from exc

            except (BackendError, OSError, ValueError, RuntimeError) as exc:
                msg = f"{type(exc).__name__}: {exc}"
                # Playwright puts the actionability reason at the END of its call
                # log, so truncating the message hides the actual cause.
                log("  " + ui.paint("⚠", ui.C.YELLOW, ui.C.BOLD)
                    + ui.paint(f"  attempt {attempt}/{self.opts.max_attempts} failed — ", ui.C.YELLOW)
                    + msg)
                item["error"] = msg[:4000]
                shot = self.opts.debug_dir / f"{_safe(job.id)}_a{attempt}.png"
                if self.backend.snapshot(shot):
                    log("  " + ui.paint(f"· screenshot: {shot}", ui.C.GREY))
                if attempt == self.opts.max_attempts:
                    self.progress.mark_failed(job.id, msg)
                    self.stats.failed += 1
                    self._done += 1
                    log("  " + ui.paint("✗", ui.C.RED, ui.C.BOLD)
                        + ui.paint(f"  gave up on {job.id}", ui.C.RED))
                else:
                    time.sleep(self.opts.retry_backoff * attempt)
                    self.backend.recover()
            finally:
                self.progress.save()


def _now() -> str:
    from .logging_utils import now_iso
    return now_iso()


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "-" for c in text)[:80]
