"""A thin end-to-end check, run on Linux, macOS and Windows in CI.

The point is portability, not coverage: these exercise the paths that differ
between platforms — path handling, text encoding, the lock file, and a whole
run through the mock backend — so a Windows regression fails a build rather
than a user's batch.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from imagegen import cli, prompts, runner


BATCH = {
    "project": "smoke",
    "output_dir": "out",
    "defaults": {"size": "256x256"},
    "images": [
        # non-ASCII on purpose: read with the locale encoding instead of UTF-8
        # this is mojibake on Windows and a crash under an ASCII locale.
        {"id": "a-1", "output": "icons/star.png", "prompt": "A gold star — café, 日本語."},
        {"id": "a-2", "output": "badges/star.png", "prompt": "A silver star badge."},
        {"id": "a-3", "output": "icons/moon.png", "prompt": "A crescent moon."},
    ],
}


@pytest.fixture
def batch(tmp_path: Path) -> Path:
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(BATCH, ensure_ascii=False), encoding="utf-8")
    return path


def test_validate(batch, capsys):
    assert cli.main(["validate", str(batch)]) == 0
    assert "café" in capsys.readouterr().out


def test_run_then_resume(batch, tmp_path):
    assert cli.main(["run", str(batch), "--backend", "mock"]) == 0
    out = tmp_path / "out"
    assert (out / "icons" / "star.png").is_file()
    assert (out / "badges" / "star.png").is_file()
    assert (out / "icons" / "moon.png").is_file()

    state = json.loads((out / ".imagegen" / "progress.json").read_text(encoding="utf-8"))
    assert sum(1 for i in state["items"].values() if i["status"] == "done") == 3

    # a second run finds nothing to do and leaves the images alone
    stamps = {p: p.stat().st_mtime_ns for p in out.rglob("*.png")}
    assert cli.main(["run", str(batch), "--backend", "mock"]) == 0
    assert {p: p.stat().st_mtime_ns for p in out.rglob("*.png")} == stamps


def test_flat_collapses_folders_and_renames_collisions(batch, tmp_path):
    jobs, errors = prompts.load_source(batch, tmp_path / "out")
    assert not errors
    prompts.flatten_outputs(jobs, tmp_path / "out")
    names = sorted(job.rel_output for job in jobs)
    # star.png existed in two folders, so both carry their folder into the
    # name; moon.png was unique and keeps the short one.
    assert names == ["badges-star.png", "icons-star.png", "moon.png"]
    assert all("/" not in n and "\\" not in n for n in names)


def test_output_paths_are_posix_in_the_manifest_but_native_on_disk(batch, tmp_path):
    jobs, _ = prompts.load_source(batch, tmp_path / "out")
    job = next(j for j in jobs if j.id == "a-1")
    assert job.rel_output == "icons/star.png"        # always forward slashes
    assert job.output == (tmp_path / "out" / "icons" / "star.png").resolve()


def test_lock_is_exclusive_and_survives_a_liveness_check(tmp_path):
    lock = tmp_path / "run.lock"
    with runner.RunLock(lock):
        assert lock.is_file()
        # the stale-lock probe must observe, never signal: on Windows
        # os.kill(pid, 0) would terminate this very process.
        assert runner._pid_alive(os.getpid()) is True
        with pytest.raises(SystemExit):
            with runner.RunLock(lock):
                pass
    assert not lock.exists()


def test_dead_pid_is_not_alive():
    # a pid that cannot exist; the probe must say so rather than raise
    assert runner._pid_alive(0x7FFFFFFF) is False


def test_spec_finds_its_brief(capsys):
    assert cli.main(["spec"]) == 0
    assert "imagegen" in capsys.readouterr().out
