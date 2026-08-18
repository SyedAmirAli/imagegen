"""Command line interface.

    imagegen run <prompt-folder> [-o OUT] [--force-background-removal] ...
    imagegen status <prompt-folder>
    imagegen validate <prompt-folder>
    imagegen init <folder>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

from . import __version__, backends, prompts
from .logging_utils import attach_file, log, rule
from .progress import Progress
from .prompts import PromptError
from .runner import RunLock, Runner

STATE_DIRNAME = ".imagegen"


def _paths(args) -> SimpleNamespace:
    prompt_dir = Path(args.prompt_dir).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve() if args.out else prompt_dir / "output"
    state_dir = out_dir / STATE_DIRNAME
    return SimpleNamespace(
        prompt_dir=prompt_dir,
        out_dir=out_dir,
        state_dir=state_dir,
        state=Path(args.state).expanduser().resolve() if getattr(args, "state", None)
        else state_dir / "progress.json",
        log=state_dir / "run.log",
        lock=state_dir / "run.lock",
        debug=state_dir / "debug",
    )


def apply_config_defaults(args, parser, config: dict) -> list[str]:
    """Let `imagegen.yaml` set option defaults for this folder.

        options:
          chrome_profile: ~/.chrome-ideogram-automation
          force_background_removal: true

    Only options left at their built-in default are touched, so anything typed
    on the command line always wins.
    """
    options = config.get("options") or {}
    if not isinstance(options, dict):
        raise SystemExit("`options` in the folder config must be a mapping")
    builtin = {a.dest: a.default for a in parser._actions}
    applied = []
    for key, value in options.items():
        dest = key.replace("-", "_")
        if dest not in builtin:
            log(f"!! ignoring unknown option {key!r} in imagegen.yaml", err=True)
            continue
        if getattr(args, dest, None) == builtin[dest]:
            setattr(args, dest, value)
            applied.append(f"{dest}={value}")
    return applied


def _load(paths) -> list:
    jobs, errors = prompts.load_folder(paths.prompt_dir, paths.out_dir)
    for path, message in errors:
        log(f"!! skipping {path.name}: {message}", err=True)
    if not jobs:
        raise SystemExit(f"no usable prompt files under {paths.prompt_dir}")
    return jobs


def _select(jobs, args) -> list:
    if args.only:
        wanted = set(args.only)
        jobs = [j for j in jobs if j.id in wanted]
        missing = wanted - {j.id for j in jobs}
        if missing:
            raise SystemExit(f"no prompt with id: {', '.join(sorted(missing))}")
    if args.match:
        import fnmatch
        jobs = [j for j in jobs
                if any(fnmatch.fnmatch(j.id, p) or fnmatch.fnmatch(j.rel_source, p)
                       for p in args.match)]
    return jobs


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_validate(args) -> int:
    paths = _paths(args)
    jobs, errors = prompts.load_folder(paths.prompt_dir, paths.out_dir)
    for path, message in errors:
        print(f"ERROR  {path}: {message}")
    print(f"\n{len(jobs)} valid prompt(s), {len(errors)} error(s) under {paths.prompt_dir}")
    if jobs:
        j = jobs[0]
        preview = j.prompt if len(j.prompt) <= 300 else j.prompt[:300] + " …"
        print("\nFirst job:")
        print(f"  id         {j.id}")
        print(f"  source     {j.rel_source}")
        print(f"  output     {j.rel_output}")
        print(f"  size       {j.size or '(generator default)'}")
        print(f"  aspect     {j.aspect or '(generator default)'}")
        print(f"  background {j.background}")
        print(f"  prompt     {preview}")
    no_size = [j for j in jobs if j.size is None]
    if no_size:
        print(f"\nnote: {len(no_size)} prompt(s) declare no size; native output is kept")
    return 1 if errors else 0


def cmd_status(args) -> int:
    paths = _paths(args)
    if not paths.state.is_file():
        print(f"no run state yet at {paths.state}")
        return 0
    jobs = _load(paths)
    progress = Progress(paths.state, paths.prompt_dir.name, args.backend)
    progress.sync(jobs)
    progress.reconcile(jobs)
    counts = {"pending": 0, "done": 0, "failed": 0, "skipped": 0}
    for item in progress.data["items"].values():
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    total = sum(counts.values())
    done = counts["done"]
    pct = (done / total * 100) if total else 0
    print(f"{paths.prompt_dir.name}: {done}/{total} done ({pct:.1f}%)  "
          f"pending {counts['pending']}  failed {counts['failed']}  skipped {counts['skipped']}")
    print(f"state   {paths.state}")
    print(f"output  {paths.out_dir}")
    if progress.data.get("last_completed_id"):
        print(f"last    {progress.data['last_completed_id']}")

    failures = [(i, item) for i, item in progress.data["items"].items()
                if item["status"] == "failed"]
    if failures:
        print(f"\nfailed ({len(failures)}) — rerun with --retry-failed:")
        for item_id, item in failures[:20]:
            print(f"  {item_id}: {(item.get('error') or '')[:140]}")
        if len(failures) > 20:
            print(f"  … and {len(failures) - 20} more")

    changed = [i for i, item in progress.data["items"].items() if item.get("prompt_changed")]
    if changed:
        print(f"\n{len(changed)} prompt(s) edited since generation — "
              f"rerun with --redo-changed to regenerate them")
    orphaned = [i for i, item in progress.data["items"].items() if item.get("orphaned")]
    if orphaned:
        print(f"{len(orphaned)} tracked item(s) no longer have a prompt file")
    return 0


def cmd_run(args) -> int:
    paths = _paths(args)
    if not args.dry_run:   # a dry run must not touch the output folder at all
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        attach_file(paths.log)

    config = prompts.load_config(paths.prompt_dir)
    applied = apply_config_defaults(args, args._parser, config)

    jobs = _load(paths)
    progress = Progress(paths.state, paths.prompt_dir.name, args.backend)
    sync = progress.sync(jobs)
    adopted = progress.reconcile(jobs) if not args.no_reconcile else 0

    if args.retry_failed:
        n = progress.requeue(("failed",))
        log(f"re-queued {n} previously failed item(s)")
    if args.redo_changed:
        n = progress.requeue_changed()
        log(f"re-queued {n} item(s) whose prompt changed")
    if not args.dry_run:
        progress.save()

    selected = _select(jobs, args)
    queue = [j for j in selected if progress.get(j.id)["status"] == "pending"]

    rule("=")
    log(f"imagegen {__version__} · backend {args.backend} · {paths.prompt_dir}")
    log(f"output   {paths.out_dir}")
    log(f"prompts  {len(jobs)} total"
        + (f", {sync['added']} new" if sync["added"] else "")
        + (f", {sync['changed']} edited" if sync["changed"] else "")
        + (f", {adopted} adopted from disk" if adopted else ""))
    # counted live: progress.counts is only refreshed on save, which a dry run skips
    done_now = sum(1 for j in jobs if progress.get(j.id)["status"] == "done")
    log(f"queue    {len(queue)} to generate · already done {done_now}/{len(jobs)}")
    if applied:
        log(f"config   defaults from imagegen.yaml: {', '.join(applied)}")
    if args.force_background_removal:
        log("background removal is FORCED for every prompt that does not ask for an "
            "opaque background (images that already have alpha are left untouched)")
    rule("=")

    if args.dry_run:
        for job in queue[: args.limit or len(queue)]:
            log(f"would generate {job.id} ({job.aspect or 'default'}) -> {job.rel_output}")
        log(f"dry run: {len(queue)} item(s) would be generated")
        return 0
    if not queue:
        log("nothing to do — everything selected is already done")
        return 0

    backend_cls = backends.get(args.backend)
    backend = backend_cls(args)
    opts = SimpleNamespace(
        limit=args.limit,
        max_attempts=args.max_attempts,
        retry_backoff=args.retry_backoff,
        min_gap=args.min_gap,
        max_gap=max(args.max_gap, args.min_gap),
        force_background_removal=args.force_background_removal,
        allow_upscale=args.allow_upscale,
        debug_dir=paths.debug,
    )

    with RunLock(paths.lock):
        stats = Runner(backend=backend, progress=progress, jobs=jobs, opts=opts).run(queue)

    rule("-")
    log(f"session: {stats.generated} generated, {stats.failed} failed"
        + (" (interrupted)" if stats.interrupted else ""))
    log(f"total:   {progress.counts['done']}/{len(jobs)} done, "
        f"{progress.counts['pending']} pending, {progress.counts['failed']} failed")
    if progress.counts["pending"] or progress.counts["failed"]:
        log("rerun the same command to continue where this stopped")
    if stats.fatal:
        return 2
    return 1 if stats.failed else 0


EXAMPLE_PROMPT = """---
id: 001-example
output: portraits/example.png
size: 1536x1536
aspect: "1:1"
background: transparent
negative: "watermark, text, extra fingers, blurry"
---
A polished studio portrait of a smiling woman in her thirties wearing a navy
blazer, three-quarter view, soft key light from the left, gentle rim light,
crisp edges, isolated subject on a fully transparent background, no backdrop,
no shadow on the ground, photorealistic, high detail.
"""

EXAMPLE_CONFIG = """# Defaults applied to every prompt file in this folder.
# Anything set in a prompt file's front-matter wins over these.
defaults:
  size: 1536x1536
  aspect: "1:1"
  background: transparent
  # prompt_suffix is appended to every prompt — handy for a shared style block.
  # prompt_suffix: "consistent studio lighting, premium finish"
"""


def cmd_init(args) -> int:
    root = Path(args.prompt_dir).expanduser().resolve()
    (root / "portraits").mkdir(parents=True, exist_ok=True)
    config = root / "imagegen.yaml"
    example = root / "portraits" / "001-example.md"
    for path, content in ((config, EXAMPLE_CONFIG), (example, EXAMPLE_PROMPT)):
        if path.exists():
            print(f"kept existing {path}")
            continue
        path.write_text(content)
        print(f"wrote {path}")
    print(f"\nNext:  imagegen validate {root}\n       imagegen run {root}")
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="imagegen",
        description="Universal, resumable batch image generation from a prompt folder.",
    )
    parser.add_argument("--version", action="version", version=f"imagegen {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("prompt_dir", help="folder containing the prompt files")
        p.add_argument("-o", "--out", default=None,
                       help="output folder (default: <prompt_dir>/output)")
        p.add_argument("--backend", default=backends.DEFAULT_BACKEND,
                       choices=sorted(backends.BACKENDS),
                       help=f"generator backend (default: {backends.DEFAULT_BACKEND})")

    p_run = sub.add_parser("run", help="generate everything still pending")
    add_common(p_run)
    p_run.add_argument("--state", default=None, help="override the progress file path")
    p_run.add_argument("--limit", type=int, default=0, help="stop after N successful images")
    p_run.add_argument("--only", action="append", default=[], metavar="ID",
                       help="generate just this id (repeatable)")
    p_run.add_argument("--match", action="append", default=[], metavar="GLOB",
                       help="only ids/paths matching this glob (repeatable)")
    p_run.add_argument("--retry-failed", action="store_true",
                       help="re-queue items that previously failed")
    p_run.add_argument("--redo-changed", action="store_true",
                       help="re-queue done items whose prompt file was edited since")
    p_run.add_argument("--no-reconcile", action="store_true",
                       help="do not adopt images already present on disk as done")
    p_run.add_argument("--force-background-removal", action="store_true",
                       help="after download, cut out the background when the image "
                            "came back with none (skipped when it is already transparent, "
                            "and for prompts that ask for an opaque background)")
    p_run.add_argument("--allow-upscale", action="store_true",
                       help="resize up to the requested size instead of keeping native")
    p_run.add_argument("--max-attempts", type=int, default=3, help="tries per image (default: 3)")
    p_run.add_argument("--retry-backoff", type=float, default=5.0,
                       help="seconds x attempt to wait before a retry")
    p_run.add_argument("--min-gap", type=float, default=4.0,
                       help="minimum pause between generations (default: 4s)")
    p_run.add_argument("--max-gap", type=float, default=9.0,
                       help="maximum pause between generations (default: 9s)")
    p_run.add_argument("--dry-run", action="store_true",
                       help="show what would be generated and exit")
    for cls in backends.BACKENDS.values():
        cls.add_arguments(p_run)
    # the run subparser carries its own option defaults, which
    # apply_config_defaults() needs to tell typed flags from untouched ones
    p_run.set_defaults(func=cmd_run, _parser=p_run)

    p_status = sub.add_parser("status", help="show progress for a prompt folder")
    add_common(p_status)
    p_status.add_argument("--state", default=None)
    p_status.set_defaults(func=cmd_status)

    p_val = sub.add_parser("validate", help="parse every prompt file and report problems")
    add_common(p_val)
    p_val.set_defaults(func=cmd_validate)

    p_init = sub.add_parser("init", help="scaffold a prompt folder")
    p_init.add_argument("prompt_dir")
    p_init.set_defaults(func=cmd_init)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "_parser", None) is None:
        args._parser = parser
    try:
        return args.func(args)
    except PromptError as exc:
        print(f"prompt error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
